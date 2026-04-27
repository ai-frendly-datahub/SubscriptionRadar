from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from main import _augment_summary_with_quality, _select_quality_articles
from subscriptionradar.models import Article, CategoryConfig, EntityDefinition, Source


def test_augment_summary_with_quality_replaces_stale_quality_warnings(tmp_path: Path) -> None:
    summary_path = tmp_path / "subscription_20260424_summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "category": "subscription",
                "warnings": [
                    "freshness gaps detected: stale=0, missing=1",
                    "collection errors detected: 2",
                    "keep me",
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    _augment_summary_with_quality(
        summary_path,
        {
            "summary": {
                "collection_error_count": 0,
                "stale_sources": 0,
                "missing_sources": 0,
            }
        },
    )

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["warnings"] == ["keep me"]
    assert summary["quality_summary"]["missing_sources"] == 0


class _FakeStorage:
    def __init__(self, articles: list[Article]) -> None:
        self.articles = articles
        self.calls: list[tuple[str, int, int]] = []

    def recent_articles(self, category: str, *, days: int, limit: int) -> list[Article]:
        self.calls.append((category, days, limit))
        return self.articles


def _make_article(source: str, *, title: str = "Title", link: str = "https://example.com/article") -> Article:
    return Article(
        title=title,
        link=link,
        summary="summary",
        published=datetime(2026, 4, 25, 12, 0, tzinfo=UTC),
        source=source,
        category="subscription",
        matched_entities={"Subscription": ["plan"]},
    )


def _make_category(source_name: str) -> CategoryConfig:
    return CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[Source(name=source_name, type="rss", url="https://example.com/feed.xml")],
        entities=[EntityDefinition(name="Subscription", display_name="Subscription", keywords=["plan"])],
    )


def test_select_quality_articles_prefers_stored_window_when_available(monkeypatch) -> None:
    monkeypatch.setattr("main.apply_source_context_entities", lambda articles, sources: articles)
    monkeypatch.setattr("main.filter_relevant_articles", lambda articles, sources: articles)

    category_cfg = _make_category("Stored Source")
    stored_article = _make_article("Stored Source")
    fallback_article = _make_article(
        "Stored Source",
        title="Fallback",
        link="https://example.com/fallback",
    )
    storage = _FakeStorage([stored_article])

    selected = _select_quality_articles(
        storage,
        category_cfg=category_cfg,
        recent_days=7,
        per_source_limit=5,
        fallback_articles=[fallback_article],
    )

    assert selected == [stored_article]
    assert storage.calls == [("subscription", 14, 500)]


def test_select_quality_articles_falls_back_when_storage_window_is_empty(monkeypatch) -> None:
    monkeypatch.setattr("main.apply_source_context_entities", lambda articles, sources: articles)
    monkeypatch.setattr("main.filter_relevant_articles", lambda articles, sources: articles)

    category_cfg = _make_category("Stored Source")
    fallback_article = _make_article("Stored Source")
    storage = _FakeStorage([])

    selected = _select_quality_articles(
        storage,
        category_cfg=category_cfg,
        recent_days=7,
        per_source_limit=5,
        fallback_articles=[fallback_article],
    )

    assert selected == [fallback_article]
