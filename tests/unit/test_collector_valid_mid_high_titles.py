"""Regression: the off-topic filter must keep the nine mid/high titles from collected data."""

from __future__ import annotations

import html
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from subscriptionradar.collector import _collect_single
from subscriptionradar.config_loader import load_category_config


# Titles copied from data/raw/2026-10-22..28. Each one is mid or high on the
# 2026-10-22~28 classification and was dropped by disabling the source.
_VALID_TITLES = {
    "Product Hunt": [
        "ilha",
        "MRRaudit",
        "MiniMax M3.1 Flash",
    ],
    "PlayStation Blog": [
        "(For Southeast Asia) Crunchyroll Arrives for PS5 and PS4 users in "
        "Indonesia, Malaysia and Thailand",
    ],
    "Nintendo Life": [
        "Capcom Data Breach Results In Unauthorised Access To More Than 11.7 "
        "Million 'CAPCOM ID' Accounts",
        "Nintendo Has Scheduled 3DS And Switch Maintenance For This Week",
        "Pokémon Unite Ending Service For Switch In March 2027",
        "Nintendo Expands Switch Online's Game Boy Library With Three More Titles",
        "PSA: Hitman: Absolution's Switch 2 Upgrade Path Is Free For Now, But Be Quick!",
    ],
}

# noise=false titles the title gate also keeps, so a mid/low boundary miss is not dropped.
_ALSO_KEPT = {
    "PlayStation Blog": [
        "PlayStation Plus Monthly Games for November: Dead Island 2, Tomb Raider "
        "IV – VI Remastered, Monster Train 2",
    ],
    "Nintendo Life": [
        "Gallery: iam8bit's Sonic Legacy Cartridges Are Stunning, But Are They " "Worth The Money?",
        "Surprise! 'Shadow Of The Tomb Raider: Definitive Edition' Has Shadow "
        "Dropped On Switch 2",
        "Nintendo Expands Switch Online's GBA Library With Three More Titles",
    ],
}

# Real taglines and sentences from data/raw/2026-10-22..28. The product-name
# titles only carry the signal here, not in the title.
_SIGNAL_SUMMARIES = {
    "ilha": "Your Claude Code and Codex limits, live in the notch",
    "MRRaudit": "Understand why your MRR differs and get a number you trust",
    "MiniMax M3.1 Flash": "MiniMax’s Flash model, 3x faster and 70% cheaper for agents",
    "Gallery: iam8bit's Sonic Legacy Cartridges Are Stunning, But Are They Worth The Money?": (
        "it's safe to say that most people were taken aback by the price."
    ),
    "Surprise! 'Shadow Of The Tomb Raider: Definitive Edition' Has Shadow "
    "Dropped On Switch 2": (
        "the dev is knocking 10% off full price on the eShop until 4th November."
    ),
}

# Noise titles from the same raw files. The title gate must drop them.
_NOISE_TITLES = {
    "Product Hunt": ["Mercury 3", "Claude Duet", "DeepCell"],
    "PlayStation Blog": [
        "Marvel’s Wolverine: Photo Mode guide",
        "Official PlayStation Podcast Episode 551: Quadruple Duty",
    ],
    "Nintendo Life": [
        "Talking Point: What Are You Playing This Weekend? (24th October)",
        "Round Up: The Reviews Are In For Nintendo Switch Sports Resort",
        "Limited Run Announces Hitman: Absolution Switch 2 Physical Release, Here's A Look",
    ],
}


# Body-only mention of the old proper noun and of subscribe. Neither is a summary keyword.
_BODY_ONLY = "fixture summary mentions ilha and subscribe"


def _response(titles: list[str], summaries: dict[str, str] | None = None) -> Mock:
    summaries = summaries or {}
    body = "".join(
        "<item>"
        f"<title>{html.escape(title)}</title>"
        f"<link>https://example.com/{index}</link>"
        f"<description>{html.escape(summaries.get(title, _BODY_ONLY))}</description>"
        "</item>"
        for index, title in enumerate(titles)
    )
    payload = f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()
    mock_response = Mock()
    mock_response.content = payload
    mock_response.raise_for_status = Mock()
    return mock_response


def _collected(
    source_name: str,
    titles: list[str],
    summaries: dict[str, str] | None = None,
) -> list[str]:
    config = load_category_config("subscription")
    source = next(source for source in config.sources if source.name == source_name)
    with patch(
        "subscriptionradar.collector._fetch_url_with_retry",
        return_value=_response(titles, summaries),
    ):
        articles = _collect_single(source, category="subscription", limit=30, timeout=5)
    return [article.title for article in articles]


def test_title_gate_keeps_nine_valid_titles_and_drops_real_noise() -> None:
    for name, valid in _VALID_TITLES.items():
        noise = _NOISE_TITLES[name]
        extra = _ALSO_KEPT.get(name, [])
        assert _collected(name, [*valid, *extra, *noise], _SIGNAL_SUMMARIES) == [*valid, *extra]


def test_include_title_keywords_ignore_summary_only_mentions() -> None:
    kept = _collected(
        "Product Hunt",
        ["Mercury 3", "ilha"],
        summaries={"ilha": _SIGNAL_SUMMARIES["ilha"]},
    )
    assert kept == ["ilha"]


# Real descriptions from data/raw/2026-10-22..28.
_GENERAL_SUMMARIES = {
    "GPT-6.1 Terra": "Fast, capable computer use at half the price",
    "Pokémon Apps Are Coming Back Online After Extended Cybersecurity Outage": (
        "Pokémon Sleep was a little later to join the party, but ended its maintenance around 10am BST."
    ),
    "Official PlayStation Podcast Episode 551: Quadruple Duty": (
        "Subscribe via Apple Podcasts, Spotify, or download here"
    ),
    '"Forward Now, Into Oblivion\'s Inky Embrace" - Darkest Dungeon II Now Has A Switch 2 Edition': (
        "A paid upgrade is also available."
    ),
}


def test_general_signals_keep_real_titles_the_proper_noun_gate_missed() -> None:
    bios = _collected(
        "Nintendo Life",
        [
            "EA Shuts Down Legendary RPG Developer BioWare",
            "Mass Effect: Universe Trailer Leaked Online As BioWare Shuts Down",
            "Talking Point: What Are You Playing This Weekend? (24th October)",
        ],
    )
    assert bios == [
        "EA Shuts Down Legendary RPG Developer BioWare",
        "Mass Effect: Universe Trailer Leaked Online As BioWare Shuts Down",
    ]

    # Labeled noise. "Includes Free Upgrade Path" does not contain the old phrase
    # "upgrade path is free", so the general word "upgrade" is what keeps it.
    upgrade = _collected(
        "Nintendo Life",
        [
            "ICYMI: Cult Of The Lamb Summons A Switch 2 Version, Includes Free Upgrade Path",
            "Round Up: The Reviews Are In For Nintendo Switch Sports Resort",
        ],
    )
    assert upgrade == [
        "ICYMI: Cult Of The Lamb Summons A Switch 2 Version, Includes Free Upgrade Path",
    ]

    priced = _collected(
        "Product Hunt",
        ["GPT-6.1 Terra", "Mercury 3"],
        summaries=_GENERAL_SUMMARIES,
    )
    assert priced == ["GPT-6.1 Terra"]

    outage = _collected(
        "Nintendo Life",
        [
            "Pokémon Apps Are Coming Back Online After Extended Cybersecurity Outage",
            "Limited Run Announces Hitman: Absolution Switch 2 Physical Release, Here's A Look",
        ],
        summaries=_GENERAL_SUMMARIES,
    )
    assert outage == [
        "Pokémon Apps Are Coming Back Online After Extended Cybersecurity Outage",
    ]


def test_summary_only_subscribe_and_upgrade_stay_noise() -> None:
    podcast = _collected(
        "PlayStation Blog",
        ["Official PlayStation Podcast Episode 551: Quadruple Duty"],
        summaries=_GENERAL_SUMMARIES,
    )
    assert podcast == []

    edition = _collected(
        "Nintendo Life",
        [
            '"Forward Now, Into Oblivion\'s Inky Embrace" - Darkest Dungeon II Now Has A '
            "Switch 2 Edition"
        ],
        summaries=_GENERAL_SUMMARIES,
    )
    assert edition == []


def test_valid_titles_exist_in_collected_raw() -> None:
    root = Path("data/raw")
    if not any(root.glob("2026-10-2[2-8]/*.jsonl")):
        pytest.skip("collected raw jsonl is not in this checkout")

    found: set[str] = set()
    for path in root.glob("2026-10-2[2-8]/*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            title = json.loads(line).get("title")
            if isinstance(title, str):
                found.add(title)

    expected = [title for titles in _VALID_TITLES.values() for title in titles]
    expected.extend(
        [
            "EA Shuts Down Legendary RPG Developer BioWare",
            "Mass Effect: Universe Trailer Leaked Online As BioWare Shuts Down",
            "ICYMI: Cult Of The Lamb Summons A Switch 2 Version, Includes Free Upgrade Path",
            "GPT-6.1 Terra",
            "Pokémon Apps Are Coming Back Online After Extended Cybersecurity Outage",
            '"Forward Now, Into Oblivion\'s Inky Embrace" - Darkest Dungeon II Now Has A Switch 2 Edition',
        ]
    )
    missing = [title for title in expected if title not in found]
    assert missing == []
