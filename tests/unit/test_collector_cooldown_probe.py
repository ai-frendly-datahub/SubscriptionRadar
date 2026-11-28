from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from radar_core.crawl_health import CrawlHealthStore

from subscriptionradar.collector import (
    PROBE_COOLDOWN_SECONDS,
    _clear_robots_cache,
    _create_probe_session,
    _retry_after_deadline,
    collect_sources,
)
from subscriptionradar.models import Source


_FEED = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Spotify plan price increases</title>
      <link>https://example.com/plan</link>
      <description>Premium plan price change</description>
      <pubDate>Wed, 04 Nov 2026 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Unrelated hardware photo</title>
      <link>https://example.com/hardware</link>
      <description>A camera on a desk</description>
      <pubDate>Wed, 04 Nov 2026 11:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>"""
_EMPTY_FEED = b"""<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""


def setup_function() -> None:
    _clear_robots_cache()


def _source(name: str = "r/SaaS") -> Source:
    return Source(name=name, type="rss", url=f"https://example.com/{name}.rss")


def _disable(path: Path, name: str, error: str, *, age_days: float) -> None:
    with CrawlHealthStore(str(path), failure_threshold=1) as store:
        store.record_failure(name, error, 1.0)
        store.flush()
        updated_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=age_days)
        store.conn.execute(
            "UPDATE crawl_health SET updated_at = ? WHERE source_name = ?",
            [updated_at, name],
        )


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _feed_response(body: bytes = _FEED) -> Mock:
    response = Mock()
    response.content = body
    response.status_code = 200
    response.headers = {}
    response.raise_for_status = Mock()
    return response


def _allow_robots(url: str, **kwargs: object) -> Mock:
    assert str(url).endswith("/robots.txt")
    assert kwargs["verify"] is True
    headers = kwargs["headers"]
    assert isinstance(headers, dict)
    assert str(headers["User-Agent"]).startswith("SubscriptionRadar/0.1")
    assert "Mozilla" not in str(headers["User-Agent"])
    response = Mock()
    response.status_code = 404
    response.text = ""
    response.headers = {}
    return response


def test_probe_session_verifies_tls_and_does_not_retry() -> None:
    session = _create_probe_session()
    try:
        assert session.verify is True
        retries = session.get_adapter("https://example.com/feed").max_retries
        total = retries if isinstance(retries, int) else retries.total
        assert total == 0
    finally:
        session.close()
    assert PROBE_COOLDOWN_SECONDS >= 86400


def test_retry_after_http_date_is_timezone_aware() -> None:
    deadline = _retry_after_deadline("Wed, 21 Oct 2030 07:28:00 GMT")
    assert deadline is not None
    assert deadline.tzinfo is not None
    assert deadline.year == 2030
    assert _retry_after_deadline("not-a-date") is None
    assert _retry_after_deadline(None) is None


def test_due_429_probe_reenables_after_one_usable_feed(tmp_path: Path, monkeypatch) -> None:
    for name in ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT"):
        monkeypatch.delenv(name, raising=False)
    db_path = tmp_path / "health.duckdb"
    source = _source("r/spotify")
    _disable(
        db_path,
        source.name,
        "429 Client Error: Too Many Requests for url: https://example.com/r/spotify.rss",
        age_days=2,
    )
    metrics: dict[str, dict[str, int]] = {}
    seen: list[dict[str, object]] = []

    def fake_session_get(url: str, **kwargs: object) -> Mock:
        seen.append(kwargs)
        assert kwargs["verify"] is True
        headers = kwargs["headers"]
        assert isinstance(headers, dict)
        assert str(headers["User-Agent"]).startswith("SubscriptionRadar/0.1")
        assert "Mozilla" not in str(headers["User-Agent"])
        return _feed_response()

    with (
        patch("subscriptionradar.collector.requests.get", side_effect=_allow_robots),
        patch("subscriptionradar.collector.requests.Session.get", side_effect=fake_session_get),
    ):
        articles, errors = collect_sources(
            [source],
            category="subscription",
            max_workers=1,
            health_db_path=str(db_path),
            source_metrics=metrics,
        )

    assert errors == []
    assert len(articles) == 2
    assert len(seen) == 1
    assert metrics[source.name] == {
        "fetched_count": 2,
        "gate_passed_count": 2,
        "excluded_count": 0,
    }
    with CrawlHealthStore(str(db_path)) as store:
        assert store.is_disabled(source.name) is False


def test_keyword_gate_counts_are_recorded_for_a_healthy_source(tmp_path: Path) -> None:
    source = Source(
        name="gated-feed",
        type="rss",
        url="https://example.com/gated.rss",
        config={"include_keywords": ["plan"]},
    )
    metrics: dict[str, dict[str, int]] = {}
    with patch(
        "subscriptionradar.collector.requests.Session.get",
        return_value=_feed_response(),
    ):
        articles, errors = collect_sources(
            [source],
            category="subscription",
            max_workers=1,
            health_db_path=str(tmp_path / "health.duckdb"),
            source_metrics=metrics,
        )

    assert errors == []
    assert [article.title for article in articles] == ["Spotify plan price increases"]
    assert metrics[source.name] == {
        "fetched_count": 2,
        "gate_passed_count": 1,
        "excluded_count": 1,
    }


def test_429_probe_is_one_request_and_honors_retry_after(tmp_path: Path) -> None:
    db_path = tmp_path / "health.duckdb"
    source = _source("r/SaaS")
    _disable(
        db_path,
        source.name,
        "429 Client Error: Too Many Requests for url: https://example.com/r/SaaS.rss",
        age_days=2,
    )
    response = requests.Response()
    response.status_code = 429
    response.headers["Retry-After"] = "7200"
    response.url = source.url
    error = requests.HTTPError(
        "429 Client Error: Too Many Requests for url: https://example.com/r/SaaS.rss",
        response=response,
    )
    calls = {"count": 0}

    def fake_session_get(url: str, **kwargs: object) -> Mock:
        calls["count"] += 1
        assert kwargs["verify"] is True
        raise error

    with (
        patch("subscriptionradar.collector.requests.get", side_effect=_allow_robots),
        patch("subscriptionradar.collector.requests.Session.get", side_effect=fake_session_get),
    ):
        articles, errors = collect_sources(
            [source],
            category="subscription",
            max_workers=1,
            health_db_path=str(db_path),
        )

    assert articles == []
    assert calls["count"] == 1
    assert any("remains disabled" in error_text for error_text in errors)
    with CrawlHealthStore(str(db_path)) as store:
        assert store.is_disabled(source.name) is True
        record = store.get_health(source.name)
        assert record is not None and record.updated_at is not None
        assert _naive_utc(record.updated_at) > datetime.now(UTC).replace(tzinfo=None) + timedelta(
            minutes=30
        )
        assert store.claim_retry(source.name) is False


def test_empty_probe_keeps_the_source_disabled(tmp_path: Path) -> None:
    db_path = tmp_path / "health.duckdb"
    source = _source("r/Streaming")
    _disable(
        db_path,
        source.name,
        "429 Client Error: Too Many Requests for url: https://example.com/r/Streaming.rss",
        age_days=3,
    )
    with (
        patch("subscriptionradar.collector.requests.get", side_effect=_allow_robots),
        patch(
            "subscriptionradar.collector.requests.Session.get",
            return_value=_feed_response(_EMPTY_FEED),
        ) as session_get,
    ):
        articles, errors = collect_sources(
            [source],
            category="subscription",
            max_workers=1,
            health_db_path=str(db_path),
        )

    assert articles == []
    assert session_get.call_count == 1
    assert any("no usable feed" in error_text for error_text in errors)
    with CrawlHealthStore(str(db_path)) as store:
        assert store.is_disabled(source.name) is True


def test_robots_disallow_does_not_request_the_feed(tmp_path: Path) -> None:
    db_path = tmp_path / "health.duckdb"
    source = _source("r/SaaS")
    _disable(
        db_path,
        source.name,
        "429 Client Error: Too Many Requests for url: https://www.reddit.com/r/SaaS/.rss",
        age_days=2,
    )

    def robots_disallow(url: str, **kwargs: object) -> Mock:
        assert str(url).endswith("/robots.txt")
        assert kwargs["verify"] is True
        response = Mock()
        response.status_code = 200
        response.text = "User-agent: *\nDisallow: /\n"
        response.headers = {}
        return response

    with (
        patch("subscriptionradar.collector.requests.get", side_effect=robots_disallow) as robots,
        patch(
            "subscriptionradar.collector.requests.Session.get",
            side_effect=AssertionError("feed requested"),
        ),
    ):
        articles, errors = collect_sources(
            [source],
            category="subscription",
            max_workers=1,
            health_db_path=str(db_path),
        )

    assert articles == []
    assert robots.call_count == 1
    assert any("robots.txt disallows" in error_text for error_text in errors)
    with CrawlHealthStore(str(db_path)) as store:
        assert store.is_disabled(source.name) is True
        assert store.claim_retry(source.name) is False


def test_probe_waits_for_cooldown_and_ignores_non_transient_errors(tmp_path: Path) -> None:
    db_path = tmp_path / "health.duckdb"
    recent = _source("r/spotify")
    forbidden = _source("blocked")
    _disable(
        db_path,
        recent.name,
        "429 Client Error: Too Many Requests for url: https://example.com/r/spotify.rss",
        age_days=0,
    )
    _disable(
        db_path,
        forbidden.name,
        "403 Client Error: Forbidden for url: https://example.com/blocked.rss",
        age_days=30,
    )
    with (
        patch(
            "subscriptionradar.collector.requests.get",
            side_effect=AssertionError("robots requested"),
        ),
        patch(
            "subscriptionradar.collector.requests.Session.get",
            side_effect=AssertionError("feed requested"),
        ),
    ):
        articles, errors = collect_sources(
            [recent, forbidden],
            category="subscription",
            max_workers=1,
            health_db_path=str(db_path),
        )

    assert articles == []
    assert errors == []
    with CrawlHealthStore(str(db_path)) as store:
        assert store.is_disabled(recent.name) is True
        assert store.is_disabled(forbidden.name) is True
