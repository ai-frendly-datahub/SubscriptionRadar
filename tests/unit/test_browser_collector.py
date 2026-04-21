from __future__ import annotations

from importlib import import_module
from types import SimpleNamespace


def test_collect_browser_sources_forwards_source_config(monkeypatch) -> None:
    module = import_module("subscriptionradar.browser_collector")
    source = import_module("subscriptionradar.models").Source(
        name="Notion Pricing",
        type="browser",
        url="https://www.notion.com/pricing",
        config={"wait_for": "body"},
    )
    captured: dict[str, object] = {}

    def fake_collect(*, sources, category, timeout, health_db_path):
        captured["sources"] = sources
        captured["category"] = category
        return [], []

    monkeypatch.setattr(module, "_BROWSER_COLLECTION_AVAILABLE", True)
    monkeypatch.setattr(module, "_core_collect", fake_collect)

    articles, errors = module.collect_browser_sources([source], "subscription")

    assert articles == []
    assert errors == []
    assert captured["category"] == "subscription"
    assert captured["sources"] == [
        {
            "name": "Notion Pricing",
            "type": "browser",
            "url": "https://www.notion.com/pricing",
            "config": {"wait_for": "body"},
        }
    ]


def test_collect_browser_sources_falls_back_when_summary_missing(monkeypatch) -> None:
    module = import_module("subscriptionradar.browser_collector")
    source = import_module("subscriptionradar.models").Source(
        name="Wavve 공지사항",
        type="browser",
        url="https://www.wavve.com/notice",
        config={"wait_for": "body"},
    )

    def fake_collect(*, sources, category, timeout, health_db_path):
        article = SimpleNamespace(
            title="Wavve(웨이브)",
            link="https://www.wavve.com/notice",
            summary=None,
            published=None,
            source="Wavve 공지사항",
            category=category,
        )
        return [article], []

    monkeypatch.setattr(module, "_BROWSER_COLLECTION_AVAILABLE", True)
    monkeypatch.setattr(module, "_core_collect", fake_collect)

    articles, errors = module.collect_browser_sources([source], "subscription")

    assert errors == []
    assert len(articles) == 1
    assert articles[0].title == "Wavve(웨이브)"
    assert articles[0].summary == "Wavve(웨이브)"
