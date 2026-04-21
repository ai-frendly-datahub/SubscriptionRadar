#!/usr/bin/env python3
"""Run DuckDB data quality checks."""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT.parent / "radar-core"))

from subscriptionradar.common.quality_checks import run_all_checks  # noqa: E402
from subscriptionradar.config_loader import (  # noqa: E402
    load_category_config,
    load_category_quality_config,
    load_settings,
)
from subscriptionradar.quality_report import build_quality_report, write_quality_report  # noqa: E402
from subscriptionradar.relevance import apply_source_context_entities, filter_relevant_articles  # noqa: E402
from subscriptionradar.storage import RadarStorage  # noqa: E402


def main() -> None:
    settings = load_settings()
    db_path = settings.database_path
    if not db_path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    with duckdb.connect(str(db_path), read_only=True) as con:
        run_all_checks(
            con,
            table_name="articles",
            null_conditions={
                "title": "title IS NULL OR title = ''",
                "link": "link IS NULL OR link = ''",
                "summary": "summary IS NULL OR summary = ''",
                "published": "published IS NULL",
            },
            text_columns=["title", "summary"],
            url_column="link",
            date_column="published",
        )

    category_cfg = load_category_config("subscription")
    quality_cfg = load_category_quality_config("subscription")
    with RadarStorage(db_path) as storage:
        recent_articles = storage.recent_articles(category_cfg.category_name, days=7, limit=1000)

    scoped_articles = filter_relevant_articles(
        apply_source_context_entities(recent_articles, category_cfg.sources),
        category_cfg.sources,
    )
    report = build_quality_report(
        category=category_cfg,
        articles=scoped_articles,
        quality_config=quality_cfg,
    )
    paths = write_quality_report(
        report,
        output_dir=settings.report_dir,
        category_name=category_cfg.category_name,
    )
    summary = report["summary"]
    print(f"quality_report={paths['latest']}")
    print(f"tracked_sources={summary['tracked_sources']}")
    print(f"fresh_sources={summary['fresh_sources']}")
    print(f"stale_sources={summary['stale_sources']}")
    print(f"missing_sources={summary['missing_sources']}")
    print(f"not_tracked_sources={summary['not_tracked_sources']}")


if __name__ == "__main__":
    main()
