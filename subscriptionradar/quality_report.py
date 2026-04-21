from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Article, CategoryConfig, Source


TRACKED_EVENT_MODEL_ORDER = [
    "pricing_page_snapshot",
    "plan_change_notice",
    "app_store_ranking",
    "churn_proxy",
]
TRACKED_EVENT_MODELS = set(TRACKED_EVENT_MODEL_ORDER)
RELEVANT_COMMUNITY_SOURCE_NAMES = {
    "r/applemusic",
    "r/cordcutters",
    "r/saas",
    "r/spotify",
    "r/streaming",
}
SUMMARY_LABELS = [
    "Vendor",
    "Vendor ID",
    "Plan",
    "Plan name",
    "Plan ID",
    "Billing cycle",
    "Region",
    "Currency",
    "Price",
    "Change type",
    "Effective date",
    "App ID",
    "Rank",
    "Market",
    "Category",
    "Source URL",
    "Metric name",
    "Metric value",
]


def build_quality_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    errors: Iterable[str] | None = None,
    quality_config: Mapping[str, object] | None = None,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    generated = _as_utc(generated_at or datetime.now(UTC))
    articles_list = list(articles)
    errors_list = [str(error) for error in (errors or [])]
    quality = _dict(quality_config or {}, "data_quality")
    freshness_sla = _dict(quality, "freshness_sla")
    event_model_config = _dict(quality, "event_models")
    tracked_event_models = _tracked_event_models(quality)

    event_rows = _build_event_rows(
        articles_list,
        category.sources,
        tracked_event_models,
        event_model_config,
    )
    source_rows = [
        _build_source_row(
            source=source,
            articles=articles_list,
            event_rows=event_rows,
            errors=errors_list,
            freshness_sla=freshness_sla,
            tracked_event_models=tracked_event_models,
            generated_at=generated,
        )
        for source in category.sources
    ]

    status_counts = Counter(str(row["status"]) for row in source_rows)
    event_counts = Counter(str(row["event_model"]) for row in event_rows)
    summary = {
        "total_sources": len(source_rows),
        "enabled_sources": sum(1 for row in source_rows if row["enabled"]),
        "tracked_sources": sum(1 for row in source_rows if row["tracked"]),
        "fresh_sources": status_counts.get("fresh", 0),
        "quiet_sources": status_counts.get("quiet", 0),
        "stale_sources": status_counts.get("stale", 0),
        "missing_sources": status_counts.get("missing", 0),
        "missing_event_sources": status_counts.get("missing_event", 0),
        "unknown_event_date_sources": status_counts.get("unknown_event_date", 0),
        "not_tracked_sources": status_counts.get("not_tracked", 0),
        "skipped_disabled_sources": status_counts.get("skipped_disabled", 0),
        "collection_error_count": len(errors_list),
    }
    for event_model in TRACKED_EVENT_MODEL_ORDER:
        summary[f"{event_model}_events"] = event_counts.get(event_model, 0)
    summary.update(
        _event_quality_summary(event_rows, source_rows, quality_config or {}, tracked_event_models)
    )
    daily_review_items = _daily_review_items(
        event_rows,
        source_rows,
        quality_config or {},
        tracked_event_models,
    )
    summary["daily_review_item_count"] = len(daily_review_items)

    return {
        "category": category.category_name,
        "generated_at": generated.isoformat(),
        "scope_note": (
            "Official pricing pages and notices are tracked separately from broad "
            "tech/media/community feeds. Broad rows require plan, price, billing, "
            "or provider-level subscription evidence before they enter reports."
        ),
        "summary": summary,
        "sources": source_rows,
        "events": event_rows,
        "daily_review_items": daily_review_items,
        "source_backlog": (quality_config or {}).get("source_backlog", {}),
        "errors": errors_list,
    }


def write_quality_report(
    report: Mapping[str, object],
    *,
    output_dir: Path,
    category_name: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = _parse_datetime(str(report.get("generated_at") or "")) or datetime.now(UTC)
    date_stamp = _as_utc(generated_at).strftime("%Y%m%d")
    latest_path = output_dir / f"{category_name}_quality.json"
    dated_path = output_dir / f"{category_name}_{date_stamp}_quality.json"
    encoded = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    latest_path.write_text(encoded + "\n", encoding="utf-8")
    dated_path.write_text(encoded + "\n", encoding="utf-8")
    return {"latest": latest_path, "dated": dated_path}


def _build_event_rows(
    articles: list[Article],
    sources: list[Source],
    tracked_event_models: set[str],
    event_model_config: Mapping[str, object],
) -> list[dict[str, Any]]:
    source_map = {source.name: source for source in sources}
    rows: list[dict[str, Any]] = []
    for article in articles:
        source = source_map.get(article.source)
        if source is None:
            continue
        event_model = _source_event_model(source)
        if event_model not in tracked_event_models:
            continue
        event_at = (
            _as_utc(article.published or article.collected_at)
            if (article.published or article.collected_at)
            else None
        )
        rows.append(_event_row(article, source, event_model, event_at, event_model_config))
    return rows


def _event_row(
    article: Article,
    source: Source,
    event_model: str,
    event_at: datetime | None,
    event_model_config: Mapping[str, object],
) -> dict[str, Any]:
    provider = _matches(article, "Provider")
    subscription = _matches(article, "Subscription")
    plan_change = _matches(article, "PlanChange")
    price_signals = _matches(article, "Price")
    price_amount = (
        _price_amount(article)
        if event_model in {"pricing_page_snapshot", "plan_change_notice"}
        else None
    )
    row: dict[str, Any] = {
        "source": article.source,
        "source_type": source.type,
        "trust_tier": source.trust_tier,
        "content_type": source.content_type,
        "collection_tier": source.collection_tier,
        "producer_role": source.producer_role,
        "info_purpose": source.info_purpose,
        "event_model": event_model,
        "title": article.title,
        "url": article.link,
        "source_url": article.link or source.url,
        "event_at": event_at.isoformat() if event_at else None,
        "subscription": subscription,
        "price": price_signals,
        "plan_change": plan_change,
        "billing_policy": _matches(article, "BillingPolicy"),
        "provider": provider,
        "service_type": _matches(article, "ServiceType"),
        "source_signal": _matches(article, "SourceSignal"),
        "vendor_id": _vendor_id(article, source, provider),
        "vendor_name": _vendor_name(article, source, provider),
        "plan_id": _plan_id(article, source, subscription),
        "plan_name": _plan_name(article, source, subscription),
        "billing_cycle": _billing_cycle(article, source, subscription),
        "region": _region(article, source),
        "currency": _currency(article),
        "price_amount": price_amount,
        "change_type": _change_type(article, source, plan_change),
        "effective_date": _summary_value(article, "Effective date"),
        "app_id": _summary_value(article, "App ID"),
        "rank": _rank(article),
        "market": _market(article, source),
        "app_category": _summary_value(article, "Category"),
        "metric_name": _metric_name(article, source),
        "metric_value": _metric_value(article, source),
    }
    canonical_key, canonical_key_status = _canonical_key(row)
    row["canonical_key"] = canonical_key
    row["canonical_key_status"] = canonical_key_status
    row["event_key"] = _event_key(row, event_model, event_at)
    row["required_field_proxy"] = _required_field_proxy(row, event_model, event_model_config)
    row["required_field_gaps"] = _required_field_gaps(row, event_model, event_model_config)
    return row


def _build_source_row(
    *,
    source: Source,
    articles: list[Article],
    event_rows: list[dict[str, Any]],
    errors: list[str],
    freshness_sla: Mapping[str, object],
    tracked_event_models: set[str],
    generated_at: datetime,
) -> dict[str, Any]:
    source_articles = [article for article in articles if article.source == source.name]
    source_errors = [error for error in errors if error.startswith(f"{source.name}:")]
    event_model = _source_event_model(source)
    source_event_rows = [
        row
        for row in event_rows
        if row["source"] == source.name and row["event_model"] == event_model
    ]
    latest_event = _latest_event(source_event_rows)
    latest_event_at = _parse_datetime(str(latest_event.get("event_at") or "")) if latest_event else None
    sla_days = _source_sla_days(source, event_model, freshness_sla)
    age_days = _age_days(generated_at, latest_event_at) if latest_event_at else None
    status = _source_status(
        source=source,
        event_model=event_model,
        tracked_event_models=tracked_event_models,
        article_count=len(source_articles),
        event_count=len(source_event_rows),
        latest_event_at=latest_event_at,
        sla_days=sla_days,
        age_days=age_days,
    )

    return {
        "source": source.name,
        "source_type": source.type,
        "enabled": source.enabled,
        "trust_tier": source.trust_tier,
        "content_type": source.content_type,
        "collection_tier": source.collection_tier,
        "producer_role": source.producer_role,
        "info_purpose": source.info_purpose,
        "tracked": event_model in tracked_event_models,
        "event_model": event_model,
        "freshness_sla_days": sla_days,
        "status": status,
        "quiet_when_no_items": bool(source.config.get("quiet_when_no_items")),
        "article_count": len(source_articles),
        "event_count": len(source_event_rows),
        "latest_event_at": latest_event_at.isoformat() if latest_event_at else None,
        "age_days": round(age_days, 2) if age_days is not None else None,
        "latest_title": str(latest_event.get("title", "")) if latest_event else "",
        "latest_url": str(latest_event.get("url", "")) if latest_event else "",
        "latest_provider": latest_event.get("provider", []) if latest_event else [],
        "latest_price": latest_event.get("price", []) if latest_event else [],
        "latest_plan_change": latest_event.get("plan_change", []) if latest_event else [],
        "latest_source_signal": latest_event.get("source_signal", []) if latest_event else [],
        "latest_canonical_key": str(latest_event.get("canonical_key", "")) if latest_event else "",
        "latest_required_field_gaps": (
            latest_event.get("required_field_gaps", []) if latest_event else []
        ),
        "errors": source_errors,
    }


def _source_status(
    *,
    source: Source,
    event_model: str,
    tracked_event_models: set[str],
    article_count: int,
    event_count: int,
    latest_event_at: datetime | None,
    sla_days: float | None,
    age_days: float | None,
) -> str:
    if not source.enabled:
        return "skipped_disabled"
    if event_model not in tracked_event_models:
        return "not_tracked"
    if article_count == 0:
        if bool(source.config.get("quiet_when_no_items")):
            return "quiet"
        return "missing"
    if event_count == 0:
        return "missing_event"
    if latest_event_at is None or age_days is None:
        return "unknown_event_date"
    if sla_days is not None and age_days > sla_days:
        return "stale"
    return "fresh"


def _tracked_event_models(quality: Mapping[str, object]) -> set[str]:
    outputs = _dict(quality, "quality_outputs")
    raw = outputs.get("tracked_event_models")
    if isinstance(raw, list):
        values = {str(item).strip() for item in raw if str(item).strip()}
        return values & TRACKED_EVENT_MODELS or set(TRACKED_EVENT_MODELS)
    return set(TRACKED_EVENT_MODELS)


def _source_event_model(source: Source) -> str:
    raw = source.config.get("event_model")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    purposes = set(source.info_purpose)
    source_name = source.name.lower()
    content_type = source.content_type.lower()

    if "app_store_ranking" in purposes:
        return "app_store_ranking"
    if content_type == "pricing" or "pricing" in purposes:
        return "pricing_page_snapshot"
    if "churn_proxy" in purposes or "cancellation" in purposes:
        return "churn_proxy"
    if source_name in RELEVANT_COMMUNITY_SOURCE_NAMES or content_type == "community":
        return "churn_proxy"
    if source_name in {
        "openview blog",
        "saas mag",
        "saastr",
        "subscription economy news",
        "subscription insider",
        "the saas podcast",
    }:
        return "churn_proxy"
    if purposes & {"billing", "bundle", "official_notice", "plan_change", "promotion"}:
        return "plan_change_notice"
    return ""


def _source_sla_days(
    source: Source,
    event_model: str,
    freshness_sla: Mapping[str, object],
) -> float | None:
    raw_source_sla = source.config.get("freshness_sla_days")
    parsed_source_sla = _as_float(raw_source_sla)
    if parsed_source_sla is not None:
        return parsed_source_sla

    by_key = freshness_sla.get(event_model)
    if isinstance(by_key, Mapping):
        return _as_float(by_key.get("max_age_days"))

    suffixed_days = _as_float(freshness_sla.get(f"{event_model}_days"))
    if suffixed_days is not None:
        return suffixed_days

    suffixed_hours = _as_float(freshness_sla.get(f"{event_model}_hours"))
    if suffixed_hours is not None:
        return suffixed_hours / 24
    return None


def _event_quality_summary(
    event_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
    tracked_event_models: set[str],
) -> dict[str, int]:
    event_counts = Counter(str(row.get("event_model") or "") for row in event_rows)
    return {
        "subscription_signal_event_count": sum(
            event_counts.get(event_model, 0) for event_model in tracked_event_models
        ),
        "official_pricing_page_event_count": sum(
            1
            for row in event_rows
            if row.get("event_model") == "pricing_page_snapshot"
            and row.get("trust_tier") == "T1_official"
        ),
        "community_churn_proxy_event_count": sum(
            1
            for row in event_rows
            if row.get("event_model") == "churn_proxy"
            and str(row.get("content_type") or "").lower() == "community"
        ),
        "plan_canonical_key_present_count": sum(
            1
            for row in event_rows
            if str(row.get("canonical_key") or "").startswith("subscription_plan:")
        ),
        "vendor_proxy_key_count": sum(
            1 for row in event_rows if row.get("canonical_key_status") == "vendor_proxy"
        ),
        "price_amount_present_count": sum(
            1 for row in event_rows if row.get("price_amount") is not None
        ),
        "currency_present_count": sum(1 for row in event_rows if row.get("currency")),
        "change_type_present_count": sum(1 for row in event_rows if row.get("change_type")),
        "app_ranking_key_present_count": sum(
            1
            for row in event_rows
            if row.get("event_model") == "app_store_ranking" and row.get("canonical_key")
        ),
        "churn_metric_present_count": sum(
            1
            for row in event_rows
            if row.get("event_model") == "churn_proxy" and row.get("metric_value") is not None
        ),
        "missing_canonical_key_count": sum(1 for row in event_rows if not row.get("canonical_key")),
        "event_required_field_gap_count": sum(
            len(row.get("required_field_gaps") or []) for row in event_rows
        ),
        "tracked_source_gap_count": sum(
            1
            for row in source_rows
            if row.get("tracked")
            and row.get("status") in {"missing", "missing_event", "unknown_event_date", "stale"}
        ),
        "missing_event_model_count": sum(
            1 for model in tracked_event_models if event_counts.get(model, 0) == 0
        ),
        "source_backlog_candidate_count": len(_source_backlog_items(quality_config)),
    }


def _daily_review_items(
    event_rows: list[dict[str, Any]],
    source_rows: list[dict[str, Any]],
    quality_config: Mapping[str, object],
    tracked_event_models: set[str],
) -> list[dict[str, Any]]:
    review: list[dict[str, Any]] = []
    for row in event_rows:
        gaps = [str(value) for value in row.get("required_field_gaps") or []]
        if gaps:
            review.append(
                {
                    "reason": "missing_required_fields",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "canonical_key": row.get("canonical_key"),
                    "required_field_gaps": gaps,
                }
            )
        if not row.get("canonical_key"):
            review.append(
                {
                    "reason": "missing_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "event_key": row.get("event_key"),
                }
            )
        if row.get("canonical_key_status") == "vendor_proxy":
            review.append(
                {
                    "reason": "vendor_proxy_canonical_key",
                    "event_model": row.get("event_model"),
                    "source": row.get("source"),
                    "title": row.get("title"),
                    "canonical_key": row.get("canonical_key"),
                }
            )

    for source in source_rows:
        if not source.get("tracked"):
            continue
        if source.get("status") in {"missing", "missing_event", "unknown_event_date", "stale"}:
            review.append(
                {
                    "reason": f"source_{source.get('status')}",
                    "source": source.get("source"),
                    "event_model": source.get("event_model"),
                    "age_days": source.get("age_days"),
                    "latest_title": source.get("latest_title"),
                }
            )

    event_counts = Counter(str(row.get("event_model") or "") for row in event_rows)
    for event_model in TRACKED_EVENT_MODEL_ORDER:
        if event_model in tracked_event_models and event_counts.get(event_model, 0) == 0:
            review.append({"reason": "missing_event_model", "event_model": event_model})

    for item in _source_backlog_items(quality_config):
        review.append(
            {
                "reason": "source_backlog_pending",
                "source": item.get("name") or item.get("id"),
                "signal_type": item.get("signal_type"),
                "activation_gate": item.get("activation_gate"),
            }
        )
    return review[:50]


def _source_backlog_items(quality_config: Mapping[str, object]) -> list[Mapping[str, object]]:
    backlog = _dict(quality_config, "source_backlog")
    candidates = backlog.get("operational_candidates")
    if not isinstance(candidates, list):
        return []
    return [item for item in candidates if isinstance(item, Mapping)]


def _required_field_proxy(
    row: Mapping[str, Any],
    event_model: str,
    event_model_config: Mapping[str, object],
) -> dict[str, bool]:
    event_config = _dict(event_model_config, event_model)
    raw_fields = event_config.get("required_fields")
    if not isinstance(raw_fields, list):
        return {}
    return {
        str(field): _field_present(row, str(field))
        for field in raw_fields
        if str(field).strip()
    }


def _required_field_gaps(
    row: Mapping[str, Any],
    event_model: str,
    event_model_config: Mapping[str, object],
) -> list[str]:
    return [
        field
        for field, present in _required_field_proxy(row, event_model, event_model_config).items()
        if not present
    ]


def _field_present(row: Mapping[str, Any], field: str) -> bool:
    normalized = field.lower()
    aliases = {
        "vendor_id": ("vendor_id", "vendor_name"),
        "plan_id": ("plan_id",),
        "price": ("price_amount",),
        "currency": ("currency",),
        "source_url": ("source_url", "url"),
        "change_type": ("change_type",),
        "app_id": ("app_id",),
        "rank": ("rank",),
        "market": ("market",),
        "category": ("app_category",),
        "metric_name": ("metric_name",),
        "metric_value": ("metric_value",),
        "source": ("source",),
    }
    for alias in aliases.get(normalized, (normalized,)):
        value = row.get(alias)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return True
    return False


def _canonical_key(row: Mapping[str, Any]) -> tuple[str, str]:
    event_model = str(row.get("event_model") or "")
    vendor_id = _slug(row.get("vendor_id") or row.get("vendor_name") or "")
    plan_id = _slug(row.get("plan_id") or "")
    currency = _slug(row.get("currency") or "")
    region = _slug(row.get("region") or "")
    if event_model == "app_store_ranking":
        app_id = _slug(row.get("app_id") or row.get("vendor_id") or "")
        market = _slug(row.get("market") or "")
        category = _slug(row.get("app_category") or "")
        if app_id and market and category:
            return f"app_store:{market}:{category}:{app_id}", "complete"
        if app_id:
            return f"app_store:{app_id}", "app_proxy"
        return "", "missing"
    if event_model == "churn_proxy":
        metric = _slug(row.get("metric_name") or "")
        if vendor_id and metric:
            return f"churn_proxy:{vendor_id}:{metric}", "complete"
        if vendor_id:
            return f"churn_proxy:{vendor_id}", "vendor_proxy"
        return "", "missing"
    if vendor_id and plan_id:
        suffix = ":".join(part for part in (plan_id, region, currency) if part)
        return f"subscription_plan:{vendor_id}:{suffix}", "complete"
    if vendor_id:
        return f"subscription_plan:{vendor_id}", "vendor_proxy"
    return "", "missing"


def _event_key(row: Mapping[str, Any], event_model: str, event_at: datetime | None) -> str:
    observed = _as_utc(event_at).strftime("%Y%m%d") if event_at else "undated"
    basis = row.get("canonical_key") or row.get("source_url") or row.get("title") or ""
    return f"{event_model}:{_digest(basis)}:{observed}"


def _vendor_id(article: Article, source: Source, provider: list[str]) -> str:
    configured = _first_non_empty(source.config.get("vendor_id"), source.config.get("provider_id"))
    if configured:
        return _slug(configured)
    labeled = _summary_value(article, "Vendor ID", "Vendor")
    if labeled:
        return _slug(labeled)
    if source.content_type == "pricing" or source.producer_role == "vendor" or source.type == "browser":
        return _slug(_vendor_name_from_source(source.name))
    if provider:
        return _slug(provider[0])
    return _slug(_vendor_name_from_source(source.name))


def _vendor_name(article: Article, source: Source, provider: list[str]) -> str:
    labeled = _summary_value(article, "Vendor")
    if labeled:
        return labeled
    if source.content_type == "pricing" or source.producer_role == "vendor" or source.type == "browser":
        return _vendor_name_from_source(source.name)
    if provider:
        return provider[0]
    return _vendor_name_from_source(source.name)


def _vendor_name_from_source(source_name: str) -> str:
    cleaned = re.sub(
        r"\b(plans?|pricing|premium|newsroom|techblog|blog|investor|relations|official|notice|customer center)\b",
        "",
        source_name,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"(공지사항|고객센터|도움말|help center)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"[&|]+", " ", cleaned)
    return " ".join(cleaned.split()) or source_name


def _plan_id(article: Article, source: Source, subscription: list[str]) -> str:
    configured = _summary_value(article, "Plan ID")
    if configured:
        return _slug(configured)
    config_default = _source_config_text(source, "plan_id", "default_plan_id", "product_id")
    if config_default:
        return _slug(config_default)
    labeled = _plan_name(article, source, subscription)
    if labeled:
        return _slug(labeled)
    return ""


def _plan_name(article: Article, source: Source, subscription: list[str]) -> str:
    labeled = _summary_value(article, "Plan", "Plan name")
    if labeled:
        return labeled
    configured = _source_config_text(source, "plan_name", "default_plan_name", "product_name")
    if configured:
        return configured
    return ""


def _billing_cycle(article: Article, source: Source, subscription: list[str]) -> str:
    labeled = _summary_value(article, "Billing cycle")
    if labeled:
        return labeled
    configured = _source_config_text(source, "billing_cycle", "default_billing_cycle")
    if configured:
        return configured
    text = _article_text(article)
    for cycle in ("monthly", "yearly", "annual", "weekly"):
        if cycle in text.lower() or cycle in [item.lower() for item in subscription]:
            return cycle
    return ""


def _region(article: Article, source: Source) -> str:
    configured = _first_non_empty(source.config.get("region"), source.config.get("country"))
    if configured:
        return configured
    return _summary_value(article, "Region")


def _currency(article: Article) -> str:
    explicit = _summary_value(article, "Currency").upper()
    if explicit:
        return explicit
    text = _article_text(article)
    if "$" in text or re.search(r"\bUSD\b", text, flags=re.IGNORECASE):
        return "USD"
    if re.search(r"\bKRW\b|원", text, flags=re.IGNORECASE):
        return "KRW"
    if re.search(r"\bEUR\b|€", text, flags=re.IGNORECASE):
        return "EUR"
    return ""


def _price_amount(article: Article) -> float | None:
    labeled = _summary_value(article, "Price")
    if labeled:
        return _extract_price_amount(labeled, require_currency=False)
    return _extract_price_amount(_article_text(article), require_currency=True)


def _extract_price_amount(text: str, *, require_currency: bool) -> float | None:
    if not text:
        return None
    if require_currency:
        patterns = [
            r"(?:[$€₩]|USD|KRW|EUR)\s*(\d[\d,]*(?:\.\d+)?)",
            r"(\d[\d,]*(?:\.\d+)?)\s*(?:원|[$€₩]|USD|KRW|EUR)",
        ]
    else:
        patterns = [r"(\d[\d,]*(?:[.,]\d+)?)"]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _parse_amount(match.group(1))
    if not require_currency and re.search(r"\bfree\b|무료", text, flags=re.IGNORECASE):
        return 0.0
    return None


def _parse_amount(raw: str) -> float | None:
    normalized = raw.strip()
    if not normalized:
        return None
    if "," in normalized and "." in normalized:
        normalized = normalized.replace(",", "")
    elif "," in normalized:
        parts = normalized.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _change_type(article: Article, source: Source, plan_change: list[str]) -> str:
    labeled = _summary_value(article, "Change type")
    if labeled:
        return labeled
    configured = _source_config_text(source, "change_type", "default_change_type")
    if configured:
        return configured
    return plan_change[0] if plan_change else ""


def _rank(article: Article) -> int | None:
    labeled = _summary_value(article, "Rank")
    match = re.search(r"\d+", labeled)
    return int(match.group(0)) if match else None


def _market(article: Article, source: Source) -> str:
    configured = _first_non_empty(source.config.get("market"), source.config.get("store_market"))
    if configured:
        return configured
    return _summary_value(article, "Market")


def _metric_name(article: Article, source: Source) -> str:
    labeled = _summary_value(article, "Metric name")
    if labeled:
        return labeled
    configured = _source_config_text(source, "metric_name", "default_metric_name")
    if configured:
        return configured
    inferred_name, _ = _infer_metric_signal(_article_text(article))
    return inferred_name or "churn_proxy"


def _metric_value(article: Article, source: Source) -> float | None:
    labeled = _summary_value(article, "Metric value")
    match = re.search(r"\d+(?:[.,]\d+)?", labeled)
    if match:
        return float(match.group(0).replace(",", "."))
    configured = _source_config_text(source, "metric_value", "default_metric_value")
    if configured:
        return _parse_amount(configured)
    _, inferred_value = _infer_metric_signal(_article_text(article))
    return inferred_value


def _source_config_text(source: Source, *keys: str) -> str:
    return _first_non_empty(*(source.config.get(key) for key in keys))


def _infer_metric_signal(text: str) -> tuple[str | None, float | None]:
    money_signal = _extract_strong_money_metric_signal(text)
    if money_signal != (None, None):
        return money_signal

    percent_match = re.search(r"(\d+(?:[.,]\d+)?)\s*%", text)
    if percent_match:
        value = _parse_amount(percent_match.group(1))
        if value is not None:
            start = max(0, percent_match.start() - 48)
            end = min(len(text), percent_match.end() + 48)
            context = text[start:end].lower()
            if "free trial" in context or "conversion" in context:
                return "conversion_rate_percent", value
            if "support" in context and "resolved" in context:
                return "support_resolution_percent", value
            if "churn" in context:
                return "churn_rate_percent", value
            if "retention" in context:
                return "retention_rate_percent", value
            if "pipeline" in context:
                return "pipeline_share_percent", value
            if "sales" in context:
                return "sales_share_percent", value
            if "growth" in context or "year over year" in context:
                return "growth_rate_percent", value
            return "percentage", value

    price_point_signal = _extract_price_point_signal(text)
    if price_point_signal != (None, None):
        return price_point_signal

    count_match = re.search(r"\b(\d[\d,]*(?:\.\d+)?)\s+(customers?|subscribers?|users?)\b", text, re.IGNORECASE)
    if count_match:
        value = _parse_amount(count_match.group(1))
        if value is not None:
            unit = count_match.group(2).lower()
            if "customer" in unit:
                return "customer_count", value
            if "subscriber" in unit:
                return "subscriber_count", value
            return "user_count", value

    return None, None


def _extract_strong_money_metric_signal(text: str) -> tuple[str | None, float | None]:
    patterns = [
        (r"\$(\d+(?:[.,]\d+)?)\s*(k|m|b)\s*arr\b", "arr"),
        (r"\$(\d+(?:[.,]\d+)?)\s*(k|m|b)\s*mrr\b", "mrr"),
        (r"\$(\d+(?:[.,]\d+)?)\s*(k|m|b)\s*(?:revenue|sales)\b", "revenue"),
        (r"\$(\d+(?:[.,]\d+)?)\s*(thousand|million|billion)\s*(?:arr)\b", "arr"),
        (r"\$(\d+(?:[.,]\d+)?)\s*(thousand|million|billion)\s*(?:mrr)\b", "mrr"),
        (r"\$(\d+(?:[.,]\d+)?)\s*(thousand|million|billion)\s*(?:package|revenue|sales)\b", "revenue"),
    ]
    for pattern, metric_name in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        amount = _scale_number(match.group(1), match.group(2))
        if amount is not None:
            return metric_name, amount

    return None, None


def _extract_price_point_signal(text: str) -> tuple[str | None, float | None]:
    lowered = text.lower()
    if "subscription" in lowered or "pricing" in lowered or "price" in lowered:
        raw_amount = _extract_price_amount(text, require_currency=True)
        if raw_amount is not None:
            return "price_point", raw_amount

    return None, None


def _scale_number(raw: str, suffix: str) -> float | None:
    amount = _parse_amount(raw)
    if amount is None:
        return None
    multipliers = {
        "k": 1_000,
        "m": 1_000_000,
        "b": 1_000_000_000,
        "thousand": 1_000,
        "million": 1_000_000,
        "billion": 1_000_000_000,
    }
    factor = multipliers.get(suffix.strip().lower())
    if factor is None:
        return amount
    return amount * factor


def _summary_value(article: Article, *labels: str) -> str:
    text = " ".join(_article_text(article).split())
    for label in labels:
        match = re.search(rf"\b{re.escape(label)}\s*[:=]\s*", text, flags=re.IGNORECASE)
        if not match:
            continue
        start = match.end()
        end = len(text)
        for next_label in SUMMARY_LABELS:
            next_match = re.search(
                rf"\b{re.escape(next_label)}\s*[:=]\s*",
                text[start:],
                flags=re.IGNORECASE,
            )
            if next_match:
                end = min(end, start + next_match.start())
        return text[start:end].strip(" \t\r\n.;,")
    return ""


def _article_text(article: Article) -> str:
    return f"{article.title} {article.summary} {article.link}"


def _first_non_empty(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _slug(value: object) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9가-힣._-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return text[:120]


def _digest(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _latest_event(event_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    dated: list[tuple[datetime, dict[str, Any]]] = []
    undated: list[dict[str, Any]] = []
    for row in event_rows:
        event_at = _parse_datetime(str(row.get("event_at") or ""))
        if event_at is not None:
            dated.append((event_at, row))
        else:
            undated.append(row)
    if dated:
        return max(dated, key=lambda item: item[0])[1]
    return undated[0] if undated else None


def _matches(article: Article, key: str) -> list[str]:
    values = article.matched_entities.get(key, [])
    if isinstance(values, list):
        return [str(value) for value in values]
    return []


def _dict(mapping: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = mapping.get(key)
    return value if isinstance(value, Mapping) else {}


def _as_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _age_days(generated_at: datetime, event_at: datetime) -> float:
    return max(0.0, (_as_utc(generated_at) - _as_utc(event_at)).total_seconds() / 86400)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_datetime(value: str) -> datetime | None:
    if not value or value == "None":
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
