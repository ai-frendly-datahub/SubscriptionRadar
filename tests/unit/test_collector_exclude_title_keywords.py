from __future__ import annotations

import html
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from subscriptionradar.collector import _collect_single, collect_sources
from subscriptionradar.config_loader import load_category_config, load_category_quality_config
from subscriptionradar.models import Source
from subscriptionradar.quality_report import build_quality_report


# Quoted from the 2026-10-29 off-topic spec. A trailing ellipsis in the spec is a
# truncation marker, so the fixture keeps only the words that were actually quoted.
_QUOTED_KEYWORD_TITLES = [
    "Today's Android app deals and freebies",
    "Fitbit Edge Review",
    "LG Promo Codes and Coupons for October 2026",
    "Ulta Promo Codes: Up to 20% Off in October 2026",
    "iPhone Duo review",
    "Round Up: The Reviews Are In For Nintendo Switch Sports Resort",
    "reviewer",
]
_KEPT_BY_SOURCE = {
    "9to5Google": [
        "LG Promo Codes and Coupons for October 2026",
        "Ulta Promo Codes: Up to 20% Off in October 2026",
        "reviewer",
    ],
    "9to5Mac": [
        "LG Promo Codes and Coupons for October 2026",
        "Ulta Promo Codes: Up to 20% Off in October 2026",
        "reviewer",
    ],
    "Engadget": [
        "Today's Android app deals and freebies",
        "LG Promo Codes and Coupons for October 2026",
        "Ulta Promo Codes: Up to 20% Off in October 2026",
        "reviewer",
    ],
    "Wired": [
        "Today's Android app deals and freebies",
        "Fitbit Edge Review",
        "iPhone Duo review",
        "Round Up: The Reviews Are In For Nintendo Switch Sports Resort",
        "reviewer",
    ],
    "CNET Tech": [
        "Today's Android app deals and freebies",
        "LG Promo Codes and Coupons for October 2026",
        "Ulta Promo Codes: Up to 20% Off in October 2026",
        "reviewer",
    ],
    "Bloomberg Technology": list(_QUOTED_KEYWORD_TITLES),
}
_DISABLED_TITLES = {
    "Product Hunt": ["Mercury 3", "Claude Duet", "DeepCell"],
    "Nintendo Life": [
        "Talking Point: What Are You Playing This Weekend? (24th October)",
        "Round Up: The Reviews Are In For Nintendo Switch Sports Resort",
    ],
    "PlayStation Blog": [
        "Marvel's Wolverine: Photo Mode guide",
        "PlayStation Store: September 2026's top downloads",
    ],
    "MKBHD": [
        "ASMR iPhone Duo Unboxing",
        "The NEW Tesla Roadster: My Honest Reaction",
    ],
}


def _response(items: list[tuple[str, str]]) -> Mock:
    body = "".join(
        "<item>"
        f"<title>{html.escape(title)}</title>"
        f"<link>https://example.com/{index}</link>"
        f"<description>{html.escape(summary)}</description>"
        "</item>"
        for index, (title, summary) in enumerate(items)
    )
    payload = f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()
    mock_response = Mock()
    mock_response.content = payload
    mock_response.raise_for_status = Mock()
    return mock_response


def _collected_titles(
    source: Source,
    titles: list[str],
    summaries: list[str] | None = None,
) -> list[str]:
    items = [
        (title, "fixture" if summaries is None else summaries[index])
        for index, title in enumerate(titles)
    ]
    with patch(
        "subscriptionradar.collector._fetch_url_with_retry",
        return_value=_response(items),
    ):
        articles = _collect_single(source, category="subscription", limit=20, timeout=5)
    return [article.title for article in articles]


def test_exclude_drops_quoted_noise_titles_and_keeps_reviewer() -> None:
    config = load_category_config("subscription")
    sources = {source.name: source for source in config.sources}

    for name, kept in _KEPT_BY_SOURCE.items():
        assert _collected_titles(sources[name], _QUOTED_KEYWORD_TITLES) == kept


def test_exclude_plural_word_boundary_hyphen_and_korean_substring() -> None:
    source = Source(
        name="Boundary Feed",
        type="rss",
        url="https://example.com/feed",
        config={
            "exclude_title_keywords": [
                "review",
                "hands-on",
                "first drive",
                "leak",
                "leaked",
                "요금제",
            ]
        },
    )

    assert _collected_titles(
        source,
        [
            "reviews",
            "reviewer",
            "preview",
            "hands-on",
            "hands-onsite",
            "first drive",
            "first driveway",
            "leak",
            "leaks",
            "leaked",
            "leaking",
            "Notion 요금제 개편",
            "요금 안내",
        ],
    ) == [
        "reviewer",
        "preview",
        "hands-onsite",
        "first driveway",
        "leaking",
        "요금 안내",
    ]


def test_exclude_matches_title_only_and_runs_after_include() -> None:
    source = Source(
        name="Both Gates",
        type="rss",
        url="https://example.com/feed",
        config={
            "include_keywords": ["subscription"],
            "exclude_title_keywords": ["review"],
        },
    )

    assert _collected_titles(
        source,
        [
            "Pixel subscription price",
            "Pixel review",
            "hardware roundup",
        ],
        [
            "a long review of the phone",
            "subscription details inside",
            "subscription mentioned only here",
        ],
    ) == ["Pixel subscription price", "hardware roundup"]


def test_missing_or_empty_exclude_passes_every_title() -> None:
    titles = [
        "Fitbit Edge Review",
        "reviewer",
        "Today's Android app deals and freebies",
    ]
    configs: tuple[dict[str, object], ...] = (
        {},
        {"exclude_title_keywords": []},
        {"exclude_title_keywords": "review"},
    )

    for config in configs:
        source = Source(name="Open Feed", type="rss", url="https://example.com/feed", config=config)
        assert _collected_titles(source, titles) == titles


def test_non_string_exclude_entries_are_ignored() -> None:
    source = Source(
        name="Open Feed",
        type="rss",
        url="https://example.com/feed",
        config={"exclude_title_keywords": ["review", 3, None]},
    )

    assert _collected_titles(
        source,
        [
            "Fitbit Edge Review",
            "reviewer",
            "Today's Android app deals and freebies",
        ],
    ) == [
        "reviewer",
        "Today's Android app deals and freebies",
    ]


def test_quoted_disabled_source_titles_pass_without_an_exclude_list() -> None:
    for name, titles in _DISABLED_TITLES.items():
        source = Source(name=name, type="rss", url="https://example.com/feed", enabled=True)
        assert _collected_titles(source, titles) == titles


def test_disabled_offtopic_sources_are_not_fetched() -> None:
    config = load_category_config("subscription")
    disabled = [source for source in config.sources if source.name == "MKBHD"]
    assert len(disabled) == 1
    assert disabled[0].enabled is False

    with patch(
        "subscriptionradar.collector.requests.Session.get",
        side_effect=AssertionError("fetched"),
    ):
        articles, errors = collect_sources(disabled, category="subscription", max_workers=1)

    assert articles == []
    assert errors == []


def test_quality_report_still_lists_disabled_offtopic_sources() -> None:
    category = load_category_config("subscription")
    report = build_quality_report(
        category=category,
        articles=[],
        quality_config=load_category_quality_config("subscription"),
        generated_at=datetime(2026, 10, 28, tzinfo=UTC),
    )

    rows = {row["source"]: row for row in report["sources"]}
    assert len(rows) == len(category.sources)
    assert rows["MKBHD"]["enabled"] is False
    assert rows["MKBHD"]["status"] == "skipped_disabled"
    for name in ("Product Hunt", "PlayStation Blog", "Nintendo Life"):
        assert rows[name]["enabled"] is True
        assert rows[name]["status"] != "skipped_disabled"
    for name in ("Apple App Store Top Free US", "Apple App Store Top Free KR"):
        assert rows[name]["enabled"] is True
        assert rows[name]["status"] != "skipped_disabled"
