from __future__ import annotations

import html
import json
import os
import re
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import requests
import structlog
from pybreaker import CircuitBreakerError
from radar_core import AdaptiveThrottler, CrawlHealthStore
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .common.validators import is_challenge_or_error_page
from .exceptions import NetworkError, ParseError, SourceError
from .models import Article, Source
from .raw_logger import RawLogger
from .resilience import get_circuit_breaker_manager


logger = structlog.get_logger(__name__)

# Identifying client name. Public feeds that reject python-requests still get a
# product token, not a browser impersonation string.
SUBSCRIPTIONRADAR_USER_AGENT = (
    "SubscriptionRadar/0.1 (+https://github.com/ai-frendly-datahub/SubscriptionRadar; public-rss)"
)
RSS_TIMEOUT_SECONDS = 45
_ENV_VAR_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": SUBSCRIPTIONRADAR_USER_AGENT,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
}
_DEFAULT_HEALTH_DB_PATH = "data/radar_data.duckdb"
_COLLECTION_CONTROL_LOCK = threading.Lock()
_ACTIVE_THROTTLER: AdaptiveThrottler | None = None
_ACTIVE_HEALTH_STORE: CrawlHealthStore | None = None


def _set_collection_controls(throttler: AdaptiveThrottler, health_store: CrawlHealthStore) -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = throttler
        _ACTIVE_HEALTH_STORE = health_store


def _clear_collection_controls() -> None:
    global _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE
    with _COLLECTION_CONTROL_LOCK:
        _ACTIVE_THROTTLER = None
        _ACTIVE_HEALTH_STORE = None


def _get_collection_controls() -> tuple[AdaptiveThrottler | None, CrawlHealthStore | None]:
    with _COLLECTION_CONTROL_LOCK:
        return _ACTIVE_THROTTLER, _ACTIVE_HEALTH_STORE


class RateLimiter:
    def __init__(self, min_interval: float = 0.5):
        self._min_interval: float = min_interval
        self._last_request: float = 0.0
        self._lock: threading.Lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            self._last_request = time.monotonic()


def _resolve_max_workers(max_workers: int | None = None) -> int:
    if max_workers is None:
        raw_value = os.environ.get("RADAR_MAX_WORKERS", "5")
        try:
            parsed = int(raw_value)
        except ValueError:
            parsed = 5
    else:
        parsed = max_workers

    return max(1, min(parsed, 10))


def _env_var_names(value: object) -> list[str]:
    raw_names: list[str] = []
    if isinstance(value, str):
        raw_names = [value]
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        raw_names = [str(item) for item in value]
    names: list[str] = []
    for item in raw_names:
        candidate = item.strip()
        if not candidate:
            continue
        if _ENV_VAR_NAME.fullmatch(candidate) is None:
            raise ValueError("required_env must be an environment variable name")
        names.append(candidate)
    return names


def missing_required_env(source: Source) -> list[str]:
    """Return required env var names that are unset. Values are never returned."""
    configured = source.config.get("required_env", source.config.get("required_env_vars"))
    missing: list[str] = []
    for name in _env_var_names(configured):
        if not os.environ.get(name, "").strip():
            missing.append(name)
    return missing


def emit_missing_secret_warning(source_name: str, env_names: str | Sequence[str]) -> None:
    """Warn once that a source was skipped. Prints env var names, never values."""
    names = _env_var_names(env_names if isinstance(env_names, str) else list(env_names))
    if not names:
        raise ValueError("required_env must be an environment variable name")
    message = f"{source_name} skipped; required env {', '.join(names)}"
    print(f"::warning title=SubscriptionRadar missing secret::{message}", flush=True)


def _create_session() -> requests.Session:
    session = requests.Session()
    session.verify = True
    session.headers.update(_DEFAULT_HEADERS)

    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[408, 500, 502, 503, 504, 522, 524],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)

    return session


def _fetch_url_with_retry(
    url: str,
    timeout: int,
    headers: dict[str, str] | None = None,
    session: requests.Session | None = None,
    source_name: str | None = None,
    throttler: AdaptiveThrottler | None = None,
    health_store: CrawlHealthStore | None = None,
    max_attempts: int = 3,
) -> requests.Response:
    """Fetch URL with retry logic on transient errors."""
    merged = {**_DEFAULT_HEADERS, **(headers or {})}
    merged["User-Agent"] = SUBSCRIPTIONRADAR_USER_AGENT
    if throttler is None or health_store is None:
        active_throttler, active_health_store = _get_collection_controls()
        throttler = throttler or active_throttler
        health_store = health_store or active_health_store

    retryable_errors = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
        requests.exceptions.HTTPError,
    )

    for attempt in range(max_attempts):
        if source_name is not None and throttler is not None:
            throttler.acquire(source_name)

        try:
            if session is not None:
                response = session.get(url, timeout=timeout, headers=merged, verify=True)
            else:
                response = requests.get(url, timeout=timeout, headers=merged, verify=True)
            response.raise_for_status()

            if source_name is not None and throttler is not None:
                throttler.record_success(source_name)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_success(source_name, delay)

            return response
        except retryable_errors as exc:
            status_code: int | None = None
            if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
                status_code = exc.response.status_code

            if source_name is not None and throttler is not None:
                retry_after: int | str | None = None
                if status_code == 429 and exc.response is not None:
                    retry_after = _parse_retry_after(exc.response.headers.get("Retry-After"))

                throttler.record_failure(source_name, retry_after=retry_after)
                if health_store is not None:
                    delay = throttler.get_current_delay(source_name)
                    health_store.record_failure(source_name, str(exc), delay)

            # A 429 is the host asking us to stop. Further immediate retries
            # make the next source on the same host fail too.
            if status_code == 429 or attempt == max_attempts - 1:
                raise

    raise RuntimeError("Retry loop exited unexpectedly")


def _parse_retry_after(value: str | None) -> int | str | None:
    if value is None:
        return None

    stripped = value.strip()
    if not stripped:
        return None

    if stripped.isdigit():
        return int(stripped)

    return stripped


def _response_is_html_page(response: requests.Response) -> bool:
    """True when a 200 body is an HTML document rather than a feed."""
    headers = getattr(response, "headers", None)
    content_type = ""
    if isinstance(headers, Mapping):
        raw_type = headers.get("Content-Type", headers.get("content-type", ""))
        content_type = str(raw_type).lower()
    if "html" in content_type:
        return True
    raw = getattr(response, "content", b"")
    if isinstance(raw, str):
        sample = raw[:300].lstrip().lower()
    elif isinstance(raw, bytes):
        sample = raw[:300].decode("utf-8", errors="ignore").lstrip().lower()
    else:
        return False
    return sample.startswith("<!doctype html") or sample.startswith("<html")


def _secret_skip(
    source: Source,
    raw_logger: RawLogger | None,
) -> tuple[list[Article], list[str]] | None:
    """Skip a source whose required env names are unset. Never records values."""
    try:
        missing_env = missing_required_env(source)
    except ValueError:
        return [], [f"{source.name}: required_env must be an environment variable name"]
    if not missing_env:
        return None
    emit_missing_secret_warning(source.name, missing_env)
    if raw_logger is not None:
        raw_logger.log_skip(source_name=source.name, required_env=missing_env)
    return [], [f"{source.name}: skipped_missing_env {', '.join(missing_env)}"]


def _without_challenge_pages(articles: list[Article]) -> list[Article]:
    return [
        article
        for article in articles
        if not is_challenge_or_error_page(article.title, article.summary)
    ]


def collect_sources(
    sources: list[Source],
    *,
    category: str,
    limit_per_source: int = 30,
    timeout: int = RSS_TIMEOUT_SECONDS,
    min_interval_per_host: float = 0.5,
    max_workers: int | None = None,
    health_db_path: str | None = None,
    raw_logger: RawLogger | None = None,
) -> tuple[list[Article], list[str]]:
    """Fetch items from all configured sources, returning articles and errors."""
    articles: list[Article] = []
    errors: list[str] = []
    manager = get_circuit_breaker_manager()
    workers = _resolve_max_workers(max_workers)
    enabled_sources = [source for source in sources if source.enabled]
    # --- Source splitting: Pass 1 (RSS/JSON) vs Pass 2 (JS/browser) ---
    _network_types = {"rss", "json"}
    _js_types = {"javascript", "browser"}
    network_sources = [s for s in enabled_sources if s.type.lower() in _network_types]
    js_sources = [s for s in enabled_sources if s.type.lower() in _js_types]
    unsupported_sources = [
        s for s in enabled_sources if s.type.lower() not in {*_network_types, *_js_types}
    ]
    errors.extend(
        f"{source.name}: Unsupported source type '{source.type}'" for source in unsupported_sources
    )
    source_hosts: dict[str, str] = {
        source.name: (urlparse(source.url).netloc.lower() or source.name)
        for source in network_sources
    }
    rate_limiters: dict[str, RateLimiter] = {}
    for host in set(source_hosts.values()):
        # Reddit's public Atom endpoint returns 429 when several feeds are
        # requested back to back. Space that host out; other feeds stay on
        # the caller interval.
        interval = 6.0 if host.endswith("reddit.com") else min_interval_per_host
        rate_limiters[host] = RateLimiter(min_interval=interval)
    host_locks: dict[str, threading.Lock] = {
        host: threading.Lock() for host in set(source_hosts.values())
    }
    throttler = AdaptiveThrottler(min_delay=max(0.001, min_interval_per_host))
    health_store = CrawlHealthStore(
        health_db_path or os.environ.get("RADAR_CRAWL_HEALTH_DB_PATH", _DEFAULT_HEALTH_DB_PATH)
    )
    _set_collection_controls(throttler, health_store)
    session = _create_session()

    def _collect_for_source(source: Source) -> tuple[list[Article], list[str]]:
        skipped = _secret_skip(source, raw_logger)
        if skipped is not None:
            return skipped
        if health_store.is_disabled(source.name):
            return [], []

        host = source_hosts[source.name]
        with host_locks[host]:
            rate_limiters[host].acquire()
            try:
                breaker = manager.get_breaker(source.name)
                result = breaker.call(
                    _collect_single,
                    source,
                    category=category,
                    limit=limit_per_source,
                    timeout=timeout,
                    session=session,
                )
                kept = _without_challenge_pages(result)
                if result and not kept:
                    return [], [f"{source.name}: collection returned only challenge or error pages"]
                return kept, []
            except CircuitBreakerError:
                return [], [f"{source.name}: Circuit breaker open (source unavailable)"]
            except SourceError as exc:
                return [], [str(exc)]
            except (NetworkError, ParseError) as exc:
                return [], [f"{source.name}: {exc}"]
            except Exception as exc:
                return [], [f"{source.name}: Unexpected error - {type(exc).__name__}: {exc}"]

    try:
        # --- Pass 1: RSS/JSON sources via ThreadPoolExecutor (parallel) ---
        if workers == 1:
            for source in network_sources:
                source_articles, source_errors = _collect_for_source(source)
                articles.extend(source_articles)
                errors.extend(source_errors)
        else:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_map: list[Future[tuple[list[Article], list[str]]]] = [
                    executor.submit(_collect_for_source, source) for source in network_sources
                ]

                for future in future_map:
                    source_articles, source_errors = future.result()
                    articles.extend(source_articles)
                    errors.extend(source_errors)

        # --- Pass 2: JavaScript/browser sources via Playwright (sequential) ---
        if js_sources:
            try:
                from .browser_collector import collect_browser_sources

                js_articles, js_errors = collect_browser_sources(js_sources, category)
                kept_js = _without_challenge_pages(js_articles)
                if js_articles and not kept_js:
                    js_errors.append("browser sources returned only challenge or error pages")
                articles.extend(kept_js)
                errors.extend(js_errors)
            except ImportError:
                logger.warning(
                    "playwright_unavailable",
                    js_source_count=len(js_sources),
                    hint="pip install 'radar-core[browser]'",
                )
    finally:
        session.close()
        health_store.close()
        _clear_collection_controls()

    return articles, errors


def _collect_single(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int = RSS_TIMEOUT_SECONDS,
    session: requests.Session | None = None,
) -> list[Article]:
    source_type = source.type.lower()
    if source_type == "rss":
        return _collect_rss_source(
            source,
            category=category,
            limit=limit,
            timeout=timeout,
            session=session,
        )
    if source_type == "json":
        return _collect_json_source(
            source,
            category=category,
            limit=limit,
            timeout=timeout,
            session=session,
        )
    raise SourceError(source.name, f"Unsupported source type '{source.type}'")


def _collect_rss_source(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:

    try:
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise NetworkError(f"Network error fetching {source.name}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SourceError(source.name, f"Request failed: {exc}", exc) from exc

    try:
        feed = feedparser.parse(response.content)
        items: list[Article] = []
        dropped_challenge = 0

        for entry in feed.entries[:limit]:
            published = _extract_datetime(entry)
            title_text = html.unescape(_entry_text(entry, "title").strip()) or "(no title)"
            summary = _entry_text(entry, "summary") or _entry_text(entry, "description")
            if not summary:
                _content = entry.get("content", [])
                if isinstance(_content, list) and _content:
                    first_item = _content[0]
                    if isinstance(first_item, Mapping):
                        value = first_item.get("value")
                        if isinstance(value, str):
                            summary = value
            link = _resolve_entry_link(entry, fallback_url=source.url)
            summary_text = html.unescape(summary.strip()) if summary.strip() else title_text
            if is_challenge_or_error_page(title_text, summary_text):
                dropped_challenge += 1
                continue

            items.append(
                Article(
                    title=title_text,
                    link=link,
                    summary=summary_text,
                    published=published,
                    source=source.name,
                    category=category,
                )
            )

        if items:
            return items
        if dropped_challenge:
            raise ParseError(
                f"Feed from {source.name} was a challenge, Cloudflare, or cookie-wall page"
            )
        if _response_is_html_page(response):
            raise ParseError(f"Feed from {source.name} returned an HTML page instead of a feed")
        return items
    except Exception as exc:
        raise ParseError(f"Failed to parse feed from {source.name}: {exc}") from exc


def _collect_json_source(
    source: Source,
    *,
    category: str,
    limit: int,
    timeout: int,
    session: requests.Session | None = None,
) -> list[Article]:
    parser_name = str(
        source.config.get("parser")
        or source.config.get("json_parser")
        or source.config.get("collector")
        or ""
    ).strip()
    if not parser_name:
        raise SourceError(source.name, "Missing json parser configuration")

    try:
        response = _fetch_url_with_retry(
            source.url,
            timeout,
            session=session,
            source_name=source.name,
        )
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        raise NetworkError(f"Network error fetching {source.name}: {exc}") from exc
    except requests.exceptions.RequestException as exc:
        raise SourceError(source.name, f"Request failed: {exc}", exc) from exc

    try:
        payload = json.loads(response.content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParseError(f"Failed to parse JSON from {source.name}: {exc}") from exc

    if parser_name == "apple_app_store_ranking":
        return _collect_apple_app_store_ranking(
            source,
            payload=payload,
            category=category,
            limit=limit,
        )
    raise SourceError(source.name, f"Unsupported json parser '{parser_name}'")


def _collect_apple_app_store_ranking(
    source: Source,
    *,
    payload: object,
    category: str,
    limit: int,
) -> list[Article]:
    if not isinstance(payload, Mapping):
        raise ParseError(
            f"Failed to parse Apple App Store ranking from {source.name}: invalid JSON"
        )

    feed = payload.get("feed")
    if not isinstance(feed, Mapping):
        raise ParseError(
            f"Failed to parse Apple App Store ranking from {source.name}: missing feed"
        )

    results = feed.get("results")
    if not isinstance(results, list):
        raise ParseError(
            f"Failed to parse Apple App Store ranking from {source.name}: missing results"
        )

    updated_at = _parse_datetime_value(feed.get("updated"))
    market = str(source.config.get("market") or feed.get("country") or "").strip().upper()
    chart_category = (
        str(source.config.get("category") or "top_free_apps").strip() or "top_free_apps"
    )
    chart_label = (
        str(source.config.get("chart_label") or "Top Free Apps").strip() or "Top Free Apps"
    )

    items: list[Article] = []
    for rank, entry in enumerate(results[:limit], start=1):
        if not isinstance(entry, Mapping):
            continue
        app_name = str(entry.get("name") or "").strip() or "(no app name)"
        app_id = str(entry.get("id") or "").strip()
        vendor_name = str(entry.get("artistName") or "").strip()
        link = str(entry.get("url") or "").strip()
        if not _is_valid_http_url(link):
            link = source.url

        summary_parts = [
            f"Vendor: {vendor_name or app_name}.",
            f"App ID: {app_id}." if app_id else "",
            f"Rank: {rank}.",
            f"Market: {market}.",
            f"Category: {chart_category}.",
            f"Source URL: {link}.",
        ]
        summary = " ".join(part for part in summary_parts if part)
        title = f"{app_name} ranks #{rank} in {market or 'global'} App Store {chart_label}"
        items.append(
            Article(
                title=title,
                link=link,
                summary=summary,
                published=updated_at,
                source=source.name,
                category=category,
            )
        )
    return items


def _resolve_entry_link(entry: Mapping[str, Any], fallback_url: str) -> str:
    primary_link = _entry_text(entry, "link").strip()
    if _is_valid_http_url(primary_link):
        return primary_link

    entry_id = _entry_text(entry, "id").strip()
    if _is_valid_http_url(entry_id):
        return entry_id

    return fallback_url


def _is_valid_http_url(value: str) -> bool:
    if not value:
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _extract_datetime(entry: Mapping[str, Any]) -> datetime | None:
    """Parse a feed entry date into a timezone-aware datetime."""
    published_parsed = entry.get("published_parsed")
    if isinstance(published_parsed, time.struct_time):
        return datetime.fromtimestamp(time.mktime(published_parsed), tz=UTC)

    updated_parsed = entry.get("updated_parsed")
    if isinstance(updated_parsed, time.struct_time):
        return datetime.fromtimestamp(time.mktime(updated_parsed), tz=UTC)

    for key in ("published", "updated", "date"):
        raw = entry.get(key)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                if dt and dt.tzinfo is None:
                    dt = dt.replace(tzinfo=UTC)
                return dt
            except Exception:
                continue
    return None


def _parse_datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except ValueError:
        return None


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""
