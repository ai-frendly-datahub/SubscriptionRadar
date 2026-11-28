from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from subscriptionradar.models import Article
from subscriptionradar.storage import RadarStorage


def _load_script_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "check_quality.py"
    spec = importlib.util.spec_from_file_location(
        "subscriptionradar_check_quality_script",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_generate_quality_artifacts_uses_latest_stored_checkpoint(
    tmp_path: Path,
    capsys,
) -> None:
    project_root = tmp_path
    (project_root / "config" / "categories").mkdir(parents=True)

    (project_root / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {
                "database_path": "data/radar_data.duckdb",
                "report_dir": "reports",
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_root / "config" / "categories" / "subscription.yaml").write_text(
        yaml.safe_dump(
            {
                "category_name": "subscription",
                "display_name": "Subscription",
                "sources": [
                    {
                        "id": "notion_pricing",
                        "name": "Notion Pricing",
                        "type": "browser",
                        "url": "https://www.notion.com/pricing",
                        "content_type": "pricing",
                        "enabled": True,
                        "info_purpose": ["pricing", "plan_change"],
                    }
                ],
                "entities": [],
                "data_quality": {
                    "quality_outputs": {
                        "tracked_event_models": ["pricing_page_snapshot"],
                    }
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    article_time = datetime.now(UTC) - timedelta(days=30)
    db_path = project_root / "data" / "radar_data.duckdb"
    with RadarStorage(db_path) as storage:
        storage.upsert_articles(
            [
                Article(
                    title="Notion pricing",
                    link="https://www.notion.com/pricing",
                    summary="Notion pricing page update.",
                    published=article_time,
                    source="Notion Pricing",
                    category="subscription",
                    matched_entities={"SourceSignal": ["pricing"]},
                )
            ]
        )

    module = _load_script_module()
    paths, report = module.generate_quality_artifacts(project_root)

    assert Path(paths["latest"]).exists()
    assert Path(paths["dated"]).exists()
    assert report["summary"]["tracked_sources"] == 1
    assert report["summary"]["pricing_page_snapshot_events"] == 1

    module.PROJECT_ROOT = project_root
    module.main()
    captured = capsys.readouterr()
    assert "quality_report=" in captured.out
    assert "tracked_sources=1" in captured.out
    assert "subscription_signal_event_count=1" in captured.out


def test_generate_quality_artifacts_keeps_a_fresh_collection_funnel(tmp_path: Path) -> None:
    project_root = tmp_path
    (project_root / "config" / "categories").mkdir(parents=True)
    (project_root / "reports").mkdir()
    (project_root / "config" / "config.yaml").write_text(
        yaml.safe_dump(
            {"database_path": "data/radar_data.duckdb", "report_dir": "reports"},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (project_root / "config" / "categories" / "subscription.yaml").write_text(
        yaml.safe_dump(
            {
                "category_name": "subscription",
                "display_name": "Subscription",
                "sources": [
                    {
                        "name": "r/spotify",
                        "type": "rss",
                        "url": "https://www.reddit.com/r/spotify/.rss",
                        "content_type": "community",
                        "enabled": True,
                    }
                ],
                "entities": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    published = datetime.now(UTC) - timedelta(hours=2)
    with RadarStorage(project_root / "data" / "radar_data.duckdb") as storage:
        storage.upsert_articles(
            [
                Article(
                    title="Spotify price hike",
                    link="https://www.reddit.com/r/spotify/comments/example",
                    summary="Premium plan price increase and cancellation.",
                    published=published,
                    source="r/spotify",
                    category="subscription",
                    matched_entities={"Price": ["price"], "Subscription": ["premium"]},
                )
            ]
        )
    previous = {
        "generated_at": datetime.now(UTC).isoformat(),
        "sources": [
            {
                "source": "r/spotify",
                "funnel_scope": "collection",
                "fetched_count": 6,
                "gate_passed_count": 2,
                "excluded_count": 4,
            }
        ],
    }
    (project_root / "reports" / "subscription_quality.json").write_text(
        json.dumps(previous),
        encoding="utf-8",
    )

    module = _load_script_module()
    _paths, report = module.generate_quality_artifacts(project_root)
    row = report["sources"][0]
    assert row["fetched_count"] == 6
    assert row["gate_passed_count"] == 2
    assert row["excluded_count"] == 4
    assert row["funnel_scope"] == "collection"
    assert row["daily_new_items"] == 1
    assert row["window_item_count"] == 1
