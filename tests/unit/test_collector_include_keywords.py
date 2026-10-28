from __future__ import annotations

from unittest.mock import Mock, patch

from subscriptionradar.collector import _collect_single, collect_sources
from subscriptionradar.config_loader import load_category_config
from subscriptionradar.models import Source


_GATE_KEYWORDS = ["game pass", "요금제"]
_XBOX_KEYWORDS = [
    "game pass",
    "playstation plus",
    "ps plus",
    "switch online",
    "subscription",
    "subscribe",
    "pricing",
    "price",
    "price hike",
    "price increase",
    "membership",
    "cancel",
    "cancellation",
    "bundle",
    "tier",
    "free trial",
    "ad-supported",
    "구독",
    "요금제",
    "구독료",
    "멤버십",
]
_UNGATED_SOURCES = (
    "PlayStation Blog",
    "Nintendo Life",
    "Product Hunt",
    "9to5Google",
    "Wired",
    "Engadget",
    "Bloomberg Technology",
)
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


def test_english_keywords_match_words_not_substrings() -> None:
    source = Source(
        name="Boundary Feed",
        type="rss",
        url="https://example.com/feed",
        config={"include_keywords": ["plan", "price increase"]},
    )
    payload = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Spotify announces a price increase</title>
      <link>https://example.com/hike</link>
      <description>Hardware roundup</description>
    </item>
    <item>
      <title>Family plan adds offline downloads</title>
      <link>https://example.com/family</link>
      <description>Weekly gadget roundup</description>
    </item>
    <item>
      <title>Plango</title>
      <link>https://example.com/plango</link>
      <description>An AI coworker that plans your week</description>
    </item>
    <item>
      <title>Planet exploration trailer</title>
      <link>https://example.com/planet</link>
      <description>A new world to explore</description>
    </item>
  </channel>
</rss>"""
    mock_response = Mock()
    mock_response.content = payload
    mock_response.raise_for_status = Mock()

    with patch("subscriptionradar.collector._fetch_url_with_retry", return_value=mock_response):
        articles = _collect_single(source, category="subscription", limit=10, timeout=5)

    assert [article.title for article in articles] == [
        "Spotify announces a price increase",
        "Family plan adds offline downloads",
    ]


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

    assert sources["Xbox Wire"].enabled is True
    assert sources["Xbox Wire"].config.get("include_keywords") == _XBOX_KEYWORDS
    for name in _UNGATED_SOURCES:
        assert sources[name].enabled is True
        assert "include_keywords" not in sources[name].config

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
