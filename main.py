from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from subscriptionradar.analyzer import apply_entity_rules
from subscriptionradar.collector import collect_sources
from subscriptionradar.common.validators import validate_article
from subscriptionradar.config_loader import (
    load_category_config,
    load_category_quality_config,
    load_settings,
)
from subscriptionradar.date_storage import apply_date_storage_policy
from subscriptionradar.quality_report import build_quality_report, write_quality_report
from subscriptionradar.raw_logger import RawLogger
from subscriptionradar.relevance import apply_source_context_entities, filter_relevant_articles
from subscriptionradar.reporter import generate_index_html, generate_report
from subscriptionradar.search_index import SearchIndex
from subscriptionradar.storage import RadarStorage
from radar_core.ontology import annotate_articles_with_ontology
from radar_core.config_loader import filter_sources


def _summary_report_path(report_dir: Path, category_name: str, quality_report: dict[str, object]) -> Path:
    existing = sorted(
        report_dir.glob(f"{category_name}_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_summary.json"),
        key=lambda path: path.stat().st_mtime,
    )
    if existing:
        return existing[-1]

    generated_at = _parse_generated_at(quality_report)
    stamp = generated_at.astimezone(UTC).strftime("%Y%m%d")
    return report_dir / f"{category_name}_{stamp}_summary.json"


def _parse_generated_at(quality_report: dict[str, object]) -> datetime:
    raw = quality_report.get("generated_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(UTC)


def _augment_summary_with_quality(summary_path: Path, quality_report: dict[str, object]) -> None:
    if not summary_path.exists():
        return

    quality_summary = quality_report.get("summary")
    if not isinstance(quality_summary, dict) or not quality_summary:
        return

    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    warnings = [
        str(warning)
        for warning in list(summary.get("warnings") or [])
        if not str(warning).startswith("collection errors detected:")
        and not str(warning).startswith("freshness gaps detected:")
    ]
    collection_errors = int(quality_summary.get("collection_error_count") or 0)
    stale_sources = int(quality_summary.get("stale_sources") or 0)
    missing_sources = int(quality_summary.get("missing_sources") or 0)
    if collection_errors:
        warnings.append(f"collection errors detected: {collection_errors}")
    if stale_sources or missing_sources:
        warnings.append(
            f"freshness gaps detected: stale={stale_sources}, missing={missing_sources}"
        )

    summary["quality_summary"] = quality_summary
    if warnings:
        summary["warnings"] = warnings
    elif "warnings" in summary:
        del summary["warnings"]
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _select_quality_articles(
    storage: RadarStorage,
    *,
    category_cfg,
    effective_sources,
    recent_days: int,
    per_source_limit: int,
    fallback_articles: list,
) -> list:
    stored_quality_articles = filter_relevant_articles(
        apply_source_context_entities(
            storage.recent_articles(
                category_cfg.category_name,
                days=max(recent_days, 14),
                limit=max(500, per_source_limit * max(len(effective_sources), 1) * 2),
            ),
            effective_sources,
        ),
        effective_sources,
    )
    return _dedupe_articles([*fallback_articles, *stored_quality_articles])


def _dedupe_articles(articles: list) -> list:
    deduped = {}
    for article in articles:
        key = f"{article.source}:{article.link or article.title}"
        deduped.setdefault(key, article)
    return list(deduped.values())


def _send_notifications(
    *,
    category_name: str,
    sources_count: int,
    collected_count: int,
    matched_count: int,
    errors_count: int,
    report_path: Path,
) -> None:
    import os
    from datetime import datetime

    email_to = os.environ.get("NOTIFICATION_EMAIL")
    webhook_url = os.environ.get("NOTIFICATION_WEBHOOK")

    if not email_to and not webhook_url:
        return

    from subscriptionradar.notifier import (
        CompositeNotifier,
        EmailNotifier,
        NotificationPayload,
        WebhookNotifier,
    )

    payload = NotificationPayload(
        category_name=category_name,
        sources_count=sources_count,
        collected_count=collected_count,
        matched_count=matched_count,
        errors_count=errors_count,
        timestamp=datetime.now(UTC),
        report_url=str(report_path),
    )

    notifiers: list[object] = []
    if email_to:
        notifiers.append(
            EmailNotifier(
                smtp_host=os.environ.get("SMTP_HOST", "localhost"),
                smtp_port=int(os.environ.get("SMTP_PORT", "587")),
                smtp_user=os.environ.get("SMTP_USER", ""),
                smtp_password=os.environ.get("SMTP_PASSWORD", ""),
                from_addr=os.environ.get("SMTP_FROM", ""),
                to_addrs=[email_to],
            )
        )
    if webhook_url:
        notifiers.append(WebhookNotifier(url=webhook_url))

    if notifiers:
        composite = CompositeNotifier(notifiers)
        _ = composite.send(payload)


def run(
    *,
    category: str,
    config_path: Path | None = None,
    categories_dir: Path | None = None,
    per_source_limit: int = 30,
    recent_days: int = 7,
    timeout: int = 15,
    keep_days: int = 90,
    keep_raw_days: int = 180,
    keep_report_days: int = 90,
    snapshot_db: bool = False,
    max_sources: int | None = None,
    exclude_sources: tuple[str, ...] | list[str] = (),
) -> Path:
    """Execute the lightweight collect -> analyze -> report pipeline."""
    settings = load_settings(config_path)
    category_cfg = load_category_config(category, categories_dir=categories_dir)
    quality_cfg = load_category_quality_config(category, categories_dir=categories_dir)

    effective_sources = filter_sources(
        category_cfg.sources,
        max_sources=max_sources,
        exclude_sources=tuple(exclude_sources or ()),
    )

    print(
        f"[Radar] Collecting '{category_cfg.display_name}' from {len(effective_sources)} sources..."
    )
    collected, errors = collect_sources(
        effective_sources,
        category=category_cfg.category_name,
        limit_per_source=per_source_limit,
        timeout=timeout,
    )
    collected = annotate_articles_with_ontology(
        collected,
        repo_name="SubscriptionRadar",
        sources_by_name={source.name: source for source in effective_sources},
        category_name=category_cfg.category_name,
        search_from=Path(__file__),
        attach_event_model_payload=True,
    )

    raw_logger = RawLogger(settings.raw_data_dir)
    for source in effective_sources:
        source_articles = [article for article in collected if article.source == source.name]
        if source_articles:
            _ = raw_logger.log(source_articles, source_name=source.name)

    analyzed = apply_entity_rules(collected, category_cfg.entities)
    classified = apply_source_context_entities(analyzed, effective_sources)
    scoped_articles = filter_relevant_articles(classified, effective_sources)

    # Validate articles for data quality
    validated_articles = []
    validation_errors = []
    for article in scoped_articles:
        is_valid, validation_msgs = validate_article(article)
        if is_valid:
            validated_articles.append(article)
        else:
            validation_errors.append(f"{article.link}: {', '.join(validation_msgs)}")

    if validation_errors:
        errors.extend(validation_errors)

    storage = RadarStorage(settings.database_path)
    storage.upsert_articles(validated_articles)
    _ = storage.delete_older_than(keep_days)

    with SearchIndex(settings.search_db_path) as search_idx:
        for article in validated_articles:
            search_idx.upsert(article.link, article.title, article.summary)

    recent_articles = filter_relevant_articles(
        apply_source_context_entities(
            storage.recent_articles(category_cfg.category_name, days=recent_days, limit=1000),
            effective_sources,
        ),
        effective_sources,
    )
    quality_articles = _select_quality_articles(
        storage,
        category_cfg=category_cfg,
        effective_sources=effective_sources,
        recent_days=recent_days,
        per_source_limit=per_source_limit,
        fallback_articles=classified if classified else recent_articles,
    )
    storage.close()

    stats = {
        "sources": len(effective_sources),
        "collected": len(scoped_articles),
        "matched": sum(1 for a in scoped_articles if a.matched_entities),
        "validated": len(validated_articles),
        "window_days": recent_days,
    }

    output_path = settings.report_dir / f"{category_cfg.category_name}_report.html"
    quality_report = build_quality_report(
        category=category_cfg,
        articles=quality_articles,
        errors=errors,
        quality_config=quality_cfg,
    )
    _ = generate_report(
        category=category_cfg,
        articles=recent_articles,
        output_path=output_path,
        stats=stats,
        errors=errors,
        quality_report=quality_report,
    )
    summary_path = _summary_report_path(settings.report_dir, category_cfg.category_name, quality_report)
    _augment_summary_with_quality(summary_path, quality_report)
    quality_paths = write_quality_report(
        quality_report,
        output_dir=settings.report_dir,
        category_name=category_cfg.category_name,
    )
    # Generate index.html
    generate_index_html(settings.report_dir)
    date_storage = apply_date_storage_policy(
        database_path=settings.database_path,
        raw_data_dir=settings.raw_data_dir,
        report_dir=settings.report_dir,
        keep_raw_days=keep_raw_days,
        keep_report_days=keep_report_days,
        snapshot_db=snapshot_db,
    )
    print(f"[Radar] Report generated at {output_path}")
    print(f"[Radar] Quality report generated at {quality_paths['latest']}")
    snapshot_path = date_storage.get("snapshot_path")
    if isinstance(snapshot_path, str) and snapshot_path:
        print(f"[Radar] Snapshot saved at {snapshot_path}")
    if errors:
        print(f"[Radar] {len(errors)} source(s) had issues. See report for details.")

    _send_notifications(
        category_name=category_cfg.category_name,
        sources_count=len(effective_sources),
        collected_count=len(scoped_articles),
        matched_count=sum(1 for a in scoped_articles if a.matched_entities),
        errors_count=len(errors),
        report_path=output_path,
    )

    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Lightweight Radar template runner")
    _ = parser.add_argument(
        "--category", required=True, help="Category name matching a YAML in config/categories/"
    )
    _ = parser.add_argument(
        "--config", type=Path, default=None, help="Path to config/config.yaml (optional)"
    )
    _ = parser.add_argument(
        "--categories-dir", type=Path, default=None, help="Custom directory for category YAML files"
    )
    _ = parser.add_argument(
        "--per-source-limit", type=int, default=30, help="Max items to pull from each source"
    )
    _ = parser.add_argument(
        "--recent-days", type=int, default=7, help="Window (days) to show in the report"
    )
    _ = parser.add_argument(
        "--timeout", type=int, default=15, help="HTTP timeout per request (seconds)"
    )
    _ = parser.add_argument(
        "--keep-days", type=int, default=90, help="Retention window for stored items"
    )
    _ = parser.add_argument(
        "--keep-raw-days", type=int, default=180, help="Retention window for raw JSONL directories"
    )
    _ = parser.add_argument(
        "--keep-report-days", type=int, default=90, help="Retention window for dated HTML reports"
    )
    _ = parser.add_argument(
        "--snapshot-db",
        action="store_true",
        default=False,
        help="Create a dated DuckDB snapshot after each run",
    )
    _ = parser.add_argument(
        "--generate-report",
        action="store_true",
        default=False,
        help="Generate HTML report after collection",
    )
    _ = parser.add_argument(
        "--max-sources",
        type=int,
        default=None,
        help="Hard cap on number of sources iterated (after --exclude-source). Default: no cap.",
    )
    _ = parser.add_argument(
        "--exclude-source",
        action="append",
        default=[],
        metavar="ID_OR_NAME",
        help="Skip this source id or name. May be repeated.",
    )
    return parser.parse_args()


def _to_path(value: object) -> Path | None:
    if isinstance(value, Path):
        return value
    return None


def _to_int(value: object, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default




def _to_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _to_str_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in cast(list[object], value) if isinstance(item, str)]
    return []
if __name__ == "__main__":
    args = cast(dict[str, object], vars(parse_args()))
    _ = run(
        category=str(args.get("category", "")),
        config_path=_to_path(args.get("config")),
        categories_dir=_to_path(args.get("categories_dir")),
        per_source_limit=_to_int(args.get("per_source_limit"), 30),
        recent_days=_to_int(args.get("recent_days"), 7),
        timeout=_to_int(args.get("timeout"), 15),
        keep_days=_to_int(args.get("keep_days"), 90),
        keep_raw_days=_to_int(args.get("keep_raw_days"), 180),
        keep_report_days=_to_int(args.get("keep_report_days"), 90),
        snapshot_db=bool(args.get("snapshot_db", False)),
        max_sources=_to_optional_int(args.get("max_sources")),
        exclude_sources=_to_str_list(args.get("exclude_source")),
    )
