from __future__ import annotations

from subscriptionradar.models import Article, Source
from subscriptionradar.relevance import apply_source_context_entities, filter_relevant_articles


def _article(
    *,
    title: str,
    source: str = "TechCrunch",
    matched_entities: dict[str, list[str]] | None = None,
) -> Article:
    return Article(
        title=title,
        link=f"https://example.com/{title.replace(' ', '-')}",
        summary=title,
        published=None,
        source=source,
        category="subscription",
        matched_entities=matched_entities or {},
    )


def test_apply_source_context_entities_adds_pricing_source_signal() -> None:
    article = _article(
        title="Notion pricing",
        source="Notion Pricing",
        matched_entities={"Subscription": ["plan"]},
    )
    source = Source(
        name="Notion Pricing",
        type="browser",
        url="https://www.notion.com/pricing",
        content_type="pricing",
        info_purpose=["pricing", "plan_change", "billing"],
    )

    classified = apply_source_context_entities([article], [source])

    assert classified[0].matched_entities["SourceSignal"] == [
        "billing",
        "plan_change",
        "pricing",
    ]


def test_filter_relevant_articles_drops_broad_noise_and_invalid_pages() -> None:
    sources = [
        Source(name="TechCrunch", type="rss", url="https://techcrunch.com/feed/"),
        Source(
            name="Notion Pricing",
            type="browser",
            url="https://www.notion.com/pricing",
            content_type="pricing",
            info_purpose=["pricing"],
        ),
        Source(
            name="SaaStr",
            type="rss",
            url="https://www.saastr.com/feed/",
        ),
    ]
    articles = [
        _article(title="AI chip startup raises funding", matched_entities={"Price": ["revenue"]}),
        _article(
            title="YouTube Premium raises prices",
            matched_entities={
                "Subscription": ["premium"],
                "Price": ["prices"],
                "Provider": ["youtube premium"],
            },
        ),
        _article(title="Access Denied", source="Notion Pricing", matched_entities={"Service": ["access"]}),
        _article(title="Basecamp pricing", source="Notion Pricing", matched_entities={}),
        _article(title="A SaaS churn warning", source="SaaStr", matched_entities={}),
    ]

    filtered = filter_relevant_articles(articles, sources)

    assert [article.title for article in filtered] == [
        "YouTube Premium raises prices",
        "Basecamp pricing",
        "A SaaS churn warning",
    ]


def test_filter_relevant_articles_keeps_only_provider_backed_app_store_rankings() -> None:
    source = Source(
        name="Apple App Store Top Free US",
        type="json",
        url="https://rss.applemarketingtools.com/api/v2/us/apps/top-free/25/apps.json",
        content_type="ranking",
        info_purpose=["app_store_ranking"],
    )
    articles = [
        _article(
            title="ChatGPT ranks #1 in US App Store Top Free Apps",
            source="Apple App Store Top Free US",
            matched_entities={"Provider": ["chatgpt"]},
        ),
        _article(
            title="setlog ranks #1 in KR App Store Top Free Apps",
            source="Apple App Store Top Free US",
            matched_entities={},
        ),
    ]

    filtered = filter_relevant_articles(articles, [source])

    assert [article.title for article in filtered] == [
        "ChatGPT ranks #1 in US App Store Top Free Apps"
    ]
