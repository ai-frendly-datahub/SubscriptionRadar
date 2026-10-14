from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests
import yaml
from radar_core.config_loader import filter_sources

from main import ensure_collection_not_empty, run
from subscriptionradar.collector import (
    RSS_TIMEOUT_SECONDS,
    SUBSCRIPTIONRADAR_USER_AGENT,
    _create_session,
    collect_sources,
)
from subscriptionradar.config_loader import load_category_config
from subscriptionradar.exceptions import EmptyCollectionError
from subscriptionradar.models import Source
from subscriptionradar.raw_logger import RawLogger

_FIXTURE = Path("tests/fixtures/challenge_feed.xml").read_bytes()


def test_coverage_config_uses_relative_paths() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    setup_cfg = Path("setup.cfg").read_text(encoding="utf-8")
    assert "relative_files = true" in pyproject
    assert "relative_files = True" in setup_cfg


def test_workflow_fails_closed_on_push_and_oversized_duckdb() -> None:
    workflow = Path(".github/workflows/radar-crawler.yml").read_text(encoding="utf-8")
    assert (
        "continue-on-error: true"
        not in workflow.split("Auto-commit data updates", 1)[1].split("Deploy to GitHub Pages", 1)[
            0
        ]
    )
    assert "steps.auto-commit.outcome == 'success'" in workflow
    assert "100 * 1024 * 1024" in workflow
    assert "is 0 bytes" in workflow
    assert "lfs: true" not in workflow
    assert "radar-core @ git+https://github.com/ai-frendly-datahub/radar-core.git@main" in workflow
    attributes = Path(".gitattributes")
    assert not attributes.exists() or "filter=lfs" not in attributes.read_text(encoding="utf-8")


def test_session_uses_identifying_user_agent_timeout_and_tls() -> None:
    session = _create_session()
    try:
        assert session.headers["User-Agent"] == SUBSCRIPTIONRADAR_USER_AGENT
        assert session.headers["User-Agent"].startswith("SubscriptionRadar/0.1")
        assert "Mozilla" not in session.headers["User-Agent"]
        assert session.verify is True
    finally:
        session.close()

    recorded: dict[str, object] = {}

    def _get(*_args: object, **kwargs: object) -> Mock:
        recorded.update(kwargs)
        response = Mock()
        response.raise_for_status.return_value = None
        response.content = _FIXTURE
        return response

    source = Source(name="Example News RSS", type="rss", url="https://example.com/feed.xml")
    with patch("subscriptionradar.collector.requests.Session.get", side_effect=_get):
        articles, errors = collect_sources([source], category="subscription", max_workers=1)

    assert errors == []
    assert [article.title for article in articles] == ["Template release notes"]
    assert recorded["timeout"] == RSS_TIMEOUT_SECONDS == 45
    assert recorded["verify"] is True
    headers = recorded["headers"]
    assert isinstance(headers, dict)
    assert str(headers["User-Agent"]).startswith("SubscriptionRadar/0.1")


def test_html_error_page_is_not_stored_as_articles() -> None:
    source = Source(name="html-feed", type="rss", url="https://example.com/rss/")
    response = Mock()
    response.raise_for_status.return_value = None
    response.headers = {"Content-Type": "text/html; charset=UTF-8"}
    response.content = b"<!DOCTYPE html><html><head><title>Error</title></head></html>"
    with patch("subscriptionradar.collector.requests.Session.get", return_value=response):
        articles, errors = collect_sources([source], category="subscription", max_workers=1)
    assert articles == []
    assert errors
    assert "HTML page" in errors[0]


def test_collector_failure_returns_empty_list_without_sample_data() -> None:
    source = Source(name="down", type="rss", url="https://example.com/feed.xml")
    with patch(
        "subscriptionradar.collector.requests.Session.get",
        side_effect=requests.exceptions.ConnectionError("down"),
    ):
        articles, errors = collect_sources([source], category="subscription", max_workers=1)

    assert articles == []
    assert errors
    blob = " ".join(errors).lower()
    assert "sample" not in blob
    assert "fake" not in blob


def test_missing_secret_warns_once_and_records_names_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = Source(
        name="Keyed API",
        type="rss",
        url="https://example.com/feed.xml",
        config={"required_env": ["SUBSCRIPTIONRADAR_TEST_TOKEN", "SUBSCRIPTIONRADAR_TEST_SECRET"]},
    )
    logger = RawLogger(tmp_path)
    with patch.dict(
        os.environ,
        {
            "SUBSCRIPTIONRADAR_TEST_TOKEN": "",
            "SUBSCRIPTIONRADAR_TEST_SECRET": "",
            "DECOY_SECRET": "super-secret-value",
        },
        clear=False,
    ):
        articles, errors = collect_sources(
            [source],
            category="subscription",
            raw_logger=logger,
            max_workers=1,
        )

    assert articles == []
    assert any("skipped_missing_env SUBSCRIPTIONRADAR_TEST_TOKEN" in error for error in errors)
    warning = capsys.readouterr().out
    assert warning.count("::warning title=SubscriptionRadar missing secret::") == 1
    assert "SUBSCRIPTIONRADAR_TEST_TOKEN" in warning
    assert "SUBSCRIPTIONRADAR_TEST_SECRET" in warning
    assert "super-secret-value" not in warning
    skip_files = list(tmp_path.rglob("*.skip.json"))
    assert len(skip_files) == 1
    text = skip_files[0].read_text(encoding="utf-8")
    assert "SUBSCRIPTIONRADAR_TEST_TOKEN" in text
    assert "SUBSCRIPTIONRADAR_TEST_SECRET" in text
    assert "super-secret-value" not in text
    assert skip_files[0].name == "Keyed API.skip.json"


def test_invalid_required_env_is_not_written(tmp_path: Path) -> None:
    source = Source(
        name="bad-config",
        type="rss",
        url="https://example.com/feed.xml",
        config={"required_env": "actual-secret-value"},
    )
    logger = RawLogger(tmp_path)
    _articles, errors = collect_sources(
        [source],
        category="subscription",
        raw_logger=logger,
        max_workers=1,
    )
    assert errors
    assert "actual-secret-value" not in errors[0]
    assert "environment variable name" in errors[0]
    assert list(tmp_path.rglob("*.skip.json")) == []


def test_disabled_sources_are_not_active(tmp_path: Path) -> None:
    category_file = tmp_path / "subscription.yaml"
    category_file.write_text(
        yaml.safe_dump(
            {
                "category_name": "subscription",
                "display_name": "Subscription",
                "sources": [
                    {
                        "name": "Paused",
                        "type": "rss",
                        "url": "https://example.com/feed.xml",
                        "enabled": False,
                    }
                ],
                "entities": [],
            }
        ),
        encoding="utf-8",
    )
    loaded = load_category_config("subscription", categories_dir=tmp_path)
    assert loaded.sources[0].enabled is False
    assert filter_sources(loaded.sources, exclude_sources=("Paused",)) == []
    with patch(
        "subscriptionradar.collector.requests.Session.get", side_effect=AssertionError("fetched")
    ):
        articles, errors = collect_sources(loaded.sources, category="subscription", max_workers=1)
    assert articles == []
    assert errors == []


def test_ensure_collection_not_empty_rejects_zero_articles() -> None:
    with pytest.raises(EmptyCollectionError):
        ensure_collection_not_empty(collected_count=0, enabled_source_count=2)


def test_ensure_collection_not_empty_allows_items_or_no_enabled_sources() -> None:
    ensure_collection_not_empty(collected_count=1, enabled_source_count=2)
    ensure_collection_not_empty(collected_count=0, enabled_source_count=0)


def test_run_fails_when_active_sources_collect_nothing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    categories_dir = tmp_path / "categories"
    categories_dir.mkdir()
    config_path.write_text(
        yaml.safe_dump(
            {
                "database_path": str(tmp_path / "data" / "radar_data.duckdb"),
                "report_dir": str(tmp_path / "reports"),
                "raw_data_dir": str(tmp_path / "data" / "raw"),
                "search_db_path": str(tmp_path / "data" / "search_index.db"),
            }
        ),
        encoding="utf-8",
    )
    (categories_dir / "test_cat.yaml").write_text(
        yaml.safe_dump(
            {
                "category_name": "test_cat",
                "display_name": "Test",
                "sources": [
                    {"name": "Empty", "type": "rss", "url": "https://example.com/feed.xml"}
                ],
                "entities": [],
            }
        ),
        encoding="utf-8",
    )
    empty_feed = (
        b"""<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>"""
    )
    response = Mock()
    response.raise_for_status.return_value = None
    response.content = empty_feed
    with (
        patch("subscriptionradar.collector.requests.Session.get", return_value=response),
        pytest.raises(EmptyCollectionError),
    ):
        run(
            category="test_cat",
            config_path=config_path,
            categories_dir=categories_dir,
            per_source_limit=5,
            recent_days=7,
            timeout=5,
        )
