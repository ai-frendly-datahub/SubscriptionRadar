from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from subscriptionradar.collector import _collect_single
from subscriptionradar.models import Source


def test_collect_single_falls_back_to_title_and_entry_id_url() -> None:
    source = Source(name="Fallback Feed", type="rss", url="https://example.com/feed")
    mock_response = Mock()
    mock_response.content = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Fallback title</title>
      <guid>https://example.com/item-1</guid>
    </item>
  </channel>
</rss>"""
    mock_response.raise_for_status = Mock()

    with patch("subscriptionradar.collector._fetch_url_with_retry", return_value=mock_response):
        articles = _collect_single(source, category="subscription", limit=5, timeout=5)

    assert len(articles) == 1
    assert articles[0].title == "Fallback title"
    assert articles[0].summary == "Fallback title"
    assert articles[0].link == "https://example.com/item-1"


def test_collect_single_falls_back_to_source_url_for_invalid_entry_id() -> None:
    source = Source(name="Fallback Feed", type="rss", url="https://example.com/feed")
    mock_response = Mock()
    mock_response.content = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Fallback title</title>
      <guid>invalid-guid</guid>
    </item>
  </channel>
</rss>"""
    mock_response.raise_for_status = Mock()

    with patch("subscriptionradar.collector._fetch_url_with_retry", return_value=mock_response):
        articles = _collect_single(source, category="subscription", limit=5, timeout=5)

    assert len(articles) == 1
    assert articles[0].title == "Fallback title"
    assert articles[0].summary == "Fallback title"
    assert articles[0].link == "https://example.com/feed"


def test_collect_single_parses_apple_app_store_ranking_json() -> None:
    source = Source(
        name="Apple App Store Top Free US",
        type="json",
        url="https://rss.applemarketingtools.com/api/v2/us/apps/top-free/5/apps.json",
        config={
            "parser": "apple_app_store_ranking",
            "market": "US",
            "category": "top_free_apps",
            "chart_label": "Top Free Apps",
        },
    )
    payload = {
        "feed": {
            "country": "us",
            "updated": "Tue, 21 Apr 2026 14:03:00 +0000",
            "results": [
                {
                    "artistName": "OpenAI OpCo, LLC",
                    "id": "6448311069",
                    "name": "ChatGPT",
                    "url": "https://apps.apple.com/us/app/chatgpt/id6448311069",
                }
            ],
        }
    }
    mock_response = Mock()
    mock_response.content = json.dumps(payload).encode("utf-8")
    mock_response.raise_for_status = Mock()

    with patch("subscriptionradar.collector._fetch_url_with_retry", return_value=mock_response):
        articles = _collect_single(source, category="subscription", limit=5, timeout=5)

    assert len(articles) == 1
    assert articles[0].title == "ChatGPT ranks #1 in US App Store Top Free Apps"
    assert articles[0].summary == (
        "Vendor: OpenAI OpCo, LLC. App ID: 6448311069. "
        "Rank: 1. Market: US. Category: top_free_apps. "
        "Source URL: https://apps.apple.com/us/app/chatgpt/id6448311069."
    )
    assert articles[0].link == "https://apps.apple.com/us/app/chatgpt/id6448311069"
    assert articles[0].published == datetime(2026, 4, 21, 14, 3, tzinfo=UTC)
