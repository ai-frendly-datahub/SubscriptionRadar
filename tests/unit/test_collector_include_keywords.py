from __future__ import annotations

from unittest.mock import Mock, patch

from subscriptionradar.collector import _collect_single, collect_sources
from subscriptionradar.config_loader import load_category_config
from subscriptionradar.models import Source


_GATE_KEYWORDS = ["game pass", "요금제"]
_GAME_KEYWORDS = [
    "game pass",
    "playstation plus",
    "ps plus",
    "switch online",
    "subscription",
    "price",
    "membership",
]
_NEWS_KEYWORDS = [
    "subscription",
    "subscribe",
    "plan",
    "pricing",
    "price hike",
    "membership",
    "구독",
    "요금제",
]
_GENERIC_TERMS = {
    "library",
    "gaming",
    "content",
    "application",
    "deal",
    "sale",
    "discount",
    "pro",
    "max",
}
_FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Xbox GAME PASS adds a tier</title>
      <link>https://example.com/pass</link>
      <description>Hardware roundup</description>
    </item>
    <item>
      <title>Weekly gadget roundup</title>
      <link>https://example.com/roundup</link>
      <description>Notion 요금제 개편을 살펴본다</description>
    </item>
    <item>
      <title>Halo campaign review</title>
      <link>https://example.com/halo</link>
      <description>We discuss the campaign length</description>
    </item>
    <item>
      <title>Robot vacuum maps the kitchen</title>
      <link>https://example.com/vacuum</link>
      <description>Battery life and navigation test</description>
    </item>
  </channel>
</rss>""".encode()


def _response() -> Mock:
    mock_response = Mock()
    mock_response.content = _FEED
    mock_response.raise_for_status = Mock()
    return mock_response


def test_include_keywords_passes_two_entries_and_blocks_two_entries() -> None:
    source = Source(
        name="Gated Feed",
        type="rss",
        url="https://example.com/feed",
        config={"include_keywords": _GATE_KEYWORDS},
    )

    with patch("subscriptionradar.collector._fetch_url_with_retry", return_value=_response()):
        articles = _collect_single(source, category="subscription", limit=10, timeout=5)

    titles = [article.title for article in articles]
    assert titles == [
        "Xbox GAME PASS adds a tier",
        "Weekly gadget roundup",
    ]
    assert "Halo campaign review" not in titles
    assert "Robot vacuum maps the kitchen" not in titles


def test_missing_include_keywords_passes_every_entry() -> None:
    source = Source(name="Open Feed", type="rss", url="https://example.com/feed")

    with patch("subscriptionradar.collector._fetch_url_with_retry", return_value=_response()):
        articles = _collect_single(source, category="subscription", limit=10, timeout=5)

    assert [article.title for article in articles] == [
        "Xbox GAME PASS adds a tier",
        "Weekly gadget roundup",
        "Halo campaign review",
        "Robot vacuum maps the kitchen",
    ]


def test_noisy_sources_are_disabled_and_keyword_gates_are_configured() -> None:
    config = load_category_config("subscription")
    sources = {source.name: source for source in config.sources}
    entities = {entity.name: entity.keywords for entity in config.entities}

    for name, marker in (
        ("Hacker News", "95%"),
        ("Disney Investor Relations", "92%"),
        ("Linus Tech Tips", "93%"),
    ):
        source = sources[name]
        assert source.enabled is False
        reason = source.config.get("skip_reason")
        assert isinstance(reason, str)
        assert marker in reason

    for name in ("Xbox Wire", "PlayStation Blog", "Nintendo Life"):
        assert sources[name].enabled is True
        assert sources[name].config.get("include_keywords") == _GAME_KEYWORDS

    for name in ("Product Hunt", "9to5Google", "Wired", "Engadget", "Bloomberg Technology"):
        assert sources[name].config.get("include_keywords") == _NEWS_KEYWORDS

    assert _GENERIC_TERMS.isdisjoint(entities["Service"])
    assert _GENERIC_TERMS.isdisjoint(entities["Price"])
    assert "game pass" in entities["Service"]
    assert "price increase" in entities["Price"]
    assert "pro plan" in entities["Subscription"]


def test_collector_skips_disabled_noise_sources_without_fetching() -> None:
    config = load_category_config("subscription")
    disabled = [
        source
        for source in config.sources
        if source.name in {"Hacker News", "Disney Investor Relations", "Linus Tech Tips"}
    ]
    assert len(disabled) == 3

    with patch(
        "subscriptionradar.collector.requests.Session.get",
        side_effect=AssertionError("fetched"),
    ):
        articles, errors = collect_sources(disabled, category="subscription", max_workers=1)

    assert articles == []
    assert errors == []
