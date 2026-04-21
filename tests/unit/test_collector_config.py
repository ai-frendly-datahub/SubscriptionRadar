from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

from subscriptionradar.collector import collect_sources
from subscriptionradar.models import Article, Source


def _article(source: str) -> Article:
    return Article(
        title=f"{source} item",
        link=f"https://example.com/{source}",
        summary="summary",
        published=datetime(2026, 4, 21, tzinfo=UTC),
        source=source,
        category="subscription",
    )


def test_collect_sources_skips_disabled_and_health_disabled_sources() -> None:
    active_rss = Source(name="Active RSS", type="rss", url="https://example.com/feed")
    active_json = Source(
        name="Active JSON",
        type="json",
        url="https://example.com/chart.json",
        config={"parser": "apple_app_store_ranking"},
    )
    active_browser = Source(name="Active Browser", type="browser", url="https://example.com/pricing")
    disabled = Source(name="Disabled", type="rss", url="https://example.com/off", enabled=False)
    health_disabled = Source(
        name="HealthDisabled",
        type="rss",
        url="https://example.com/health",
    )

    mock_breaker = Mock()
    mock_breaker.call.side_effect = lambda func, *args, **kwargs: func(*args, **kwargs)
    mock_manager = Mock()
    mock_manager.get_breaker.return_value = mock_breaker
    fake_session = Mock()
    fake_health = Mock()
    fake_health.is_disabled.side_effect = lambda name: name == "HealthDisabled"

    with (
        patch("subscriptionradar.collector.get_circuit_breaker_manager", return_value=mock_manager),
        patch("subscriptionradar.collector._create_session", return_value=fake_session),
        patch("subscriptionradar.collector.CrawlHealthStore", return_value=fake_health),
        patch(
            "subscriptionradar.collector._collect_single",
            side_effect=[[ _article("Active RSS") ], [ _article("Active JSON") ]],
        ) as mock_single,
        patch(
            "subscriptionradar.browser_collector.collect_browser_sources",
            return_value=([_article("Active Browser")], []),
        ) as mock_browser,
    ):
        articles, errors = collect_sources(
            [active_rss, active_json, active_browser, disabled, health_disabled],
            category="subscription",
            max_workers=1,
        )

    assert [article.source for article in articles] == [
        "Active RSS",
        "Active JSON",
        "Active Browser",
    ]
    assert errors == []
    assert mock_single.call_count == 2
    mock_browser.assert_called_once()
