from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from subscriptionradar.models import Article, CategoryConfig, Source
from subscriptionradar.quality_report import build_quality_report, write_quality_report


def _article(
    *,
    source: str,
    title: str,
    published: datetime | None,
    matched_entities: dict[str, list[str]] | None = None,
) -> Article:
    return Article(
        title=title,
        link=f"https://example.com/{source}/{title}".replace(" ", "-"),
        summary=title,
        published=published,
        source=source,
        category="subscription",
        matched_entities=matched_entities or {},
    )


def test_build_quality_report_tracks_subscription_source_statuses() -> None:
    now = datetime(2026, 4, 13, tzinfo=UTC)
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[
            Source(
                name="Notion Pricing",
                type="browser",
                url="https://www.notion.com/pricing",
                content_type="pricing",
                info_purpose=["pricing", "plan_change"],
            ),
            Source(
                name="Spotify Newsroom",
                type="rss",
                url="https://newsroom.spotify.com/feed",
                trust_tier="T1_official",
                producer_role="vendor",
                info_purpose=["official_news", "plan_change"],
            ),
            Source(
                name="r/cordcutters",
                type="rss",
                url="https://www.reddit.com/r/cordcutters/.rss",
                content_type="community",
                info_purpose=["community", "cancellation"],
            ),
            Source(name="TechCrunch", type="rss", url="https://techcrunch.com/feed/"),
        ],
        entities=[],
    )
    articles = [
        _article(
            source="Notion Pricing",
            title="Notion pricing",
            published=now - timedelta(days=1),
            matched_entities={"SourceSignal": ["pricing"]},
        ),
        _article(
            source="Spotify Newsroom",
            title="Spotify plan change",
            published=now - timedelta(days=4),
            matched_entities={"PlanChange": ["plan change"]},
        ),
        _article(
            source="r/cordcutters",
            title="Canceling streaming",
            published=now - timedelta(days=2),
            matched_entities={"BillingPolicy": ["cancellation"]},
        ),
    ]

    report = build_quality_report(
        category=category,
        articles=articles,
        quality_config={
            "data_quality": {
                "quality_outputs": {
                    "tracked_event_models": [
                        "pricing_page_snapshot",
                        "plan_change_notice",
                        "churn_proxy",
                    ]
                },
                "freshness_sla": {
                    "pricing_page_snapshot_days": 7,
                    "plan_change_notice_days": 3,
                    "churn_proxy_days": 30,
                },
            }
        },
        generated_at=now,
    )

    summary = report["summary"]
    assert summary["tracked_sources"] == 3
    assert summary["fresh_sources"] == 2
    assert summary["stale_sources"] == 1
    assert summary["not_tracked_sources"] == 1
    assert summary["pricing_page_snapshot_events"] == 1
    assert summary["plan_change_notice_events"] == 1
    assert summary["churn_proxy_events"] == 1
    assert summary["subscription_signal_event_count"] == 3
    assert summary["vendor_proxy_key_count"] >= 1


def test_write_quality_report_writes_latest_and_dated_json(tmp_path) -> None:
    report = {
        "category": "subscription",
        "generated_at": "2026-04-13T00:00:00+00:00",
        "summary": {},
        "sources": [],
        "events": [],
    }

    paths = write_quality_report(report, output_dir=tmp_path, category_name="subscription")

    assert paths["latest"].name == "subscription_quality.json"
    assert paths["dated"].name == "subscription_20260413_quality.json"
    assert json.loads(paths["latest"].read_text(encoding="utf-8"))["category"] == "subscription"


def test_build_quality_report_extracts_plan_price_keys_and_gaps() -> None:
    now = datetime(2026, 4, 14, tzinfo=UTC)
    source = Source(
        name="Notion Pricing",
        type="browser",
        url="https://www.notion.com/pricing",
        content_type="pricing",
        trust_tier="T1_official",
        producer_role="vendor",
        info_purpose=["pricing", "billing"],
        config={"region": "US"},
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Notion Pricing",
        link="https://www.notion.com/pricing",
        summary="Vendor: Notion. Plan: Plus. Price: $10. Currency: USD. Billing cycle: monthly.",
        published=now,
        source="Notion Pricing",
        category="subscription",
        matched_entities={
            "Provider": ["notion"],
            "Subscription": ["plus", "monthly"],
            "Price": ["price", "pricing"],
            "SourceSignal": ["pricing"],
        },
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["pricing_page_snapshot"]},
                "event_models": {
                    "pricing_page_snapshot": {
                        "required_fields": [
                            "vendor_id",
                            "plan_id",
                            "price",
                            "currency",
                            "source_url",
                        ]
                    }
                },
            },
            "source_backlog": {
                "operational_candidates": [
                    {
                        "name": "Official pricing page diff store",
                        "signal_type": "pricing_page_snapshot",
                        "activation_gate": "HTML snapshot retention",
                    }
                ]
            },
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["vendor_id"] == "notion"
    assert event["plan_id"] == "plus"
    assert event["price_amount"] == 10.0
    assert event["currency"] == "USD"
    assert event["canonical_key"] == "subscription_plan:notion:plus:us:usd"
    assert event["canonical_key_status"] == "complete"
    assert event["required_field_gaps"] == []
    assert report["summary"]["plan_canonical_key_present_count"] == 1
    assert report["summary"]["price_amount_present_count"] == 1
    assert any(
        item["reason"] == "source_backlog_pending"
        for item in report["daily_review_items"]
    )


def test_build_quality_report_flags_plan_price_required_gaps() -> None:
    now = datetime(2026, 4, 14, tzinfo=UTC)
    source = Source(
        name="Netflix Plans & Pricing",
        type="browser",
        url="https://www.netflix.com/pricing",
        content_type="pricing",
        trust_tier="T1_official",
        info_purpose=["pricing", "billing"],
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Plans and Pricing | Netflix Help Center",
        link="https://www.netflix.com/pricing",
        summary="Netflix subscription plans and billing options.",
        published=now,
        source="Netflix Plans & Pricing",
        category="subscription",
        matched_entities={"Provider": ["netflix"], "Price": ["pricing"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["pricing_page_snapshot"]},
                "event_models": {
                    "pricing_page_snapshot": {
                        "required_fields": [
                            "vendor_id",
                            "plan_id",
                            "price",
                            "currency",
                            "source_url",
                        ]
                    }
                },
            }
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["canonical_key"] == "subscription_plan:netflix"
    assert event["canonical_key_status"] == "vendor_proxy"
    assert set(event["required_field_gaps"]) == {"plan_id", "price", "currency"}
    assert report["summary"]["event_required_field_gap_count"] == 3
    assert any(
        item["reason"] == "missing_required_fields"
        for item in report["daily_review_items"]
    )


def test_build_quality_report_requires_currency_context_for_unlabeled_prices() -> None:
    now = datetime(2026, 4, 14, tzinfo=UTC)
    source = Source(
        name="Netflix Plans & Pricing",
        type="browser",
        url="https://www.netflix.com/pricing",
        content_type="pricing",
        trust_tier="T1_official",
        info_purpose=["pricing", "billing"],
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    quality_config = {
        "data_quality": {
            "quality_outputs": {"tracked_event_models": ["pricing_page_snapshot"]},
            "event_models": {
                "pricing_page_snapshot": {
                    "required_fields": [
                        "vendor_id",
                        "plan_id",
                        "price",
                        "currency",
                        "source_url",
                    ]
                }
            },
        }
    }
    generic_number = Article(
        title="Plans and Pricing | Netflix Help Center",
        link="https://www.netflix.com/pricing",
        summary="Netflix supports 2 screens and includes a free trial notice.",
        published=now,
        source="Netflix Plans & Pricing",
        category="subscription",
        matched_entities={"Provider": ["netflix"], "Price": ["pricing"]},
    )
    currency_number = Article(
        title="Plans and Pricing | Netflix Help Center",
        link="https://www.netflix.com/pricing",
        summary="Netflix standard plan billing starts at KRW 17,000 monthly.",
        published=now,
        source="Netflix Plans & Pricing",
        category="subscription",
        matched_entities={"Provider": ["netflix"], "Price": ["pricing"]},
    )

    generic_report = build_quality_report(
        category=category,
        articles=[generic_number],
        quality_config=quality_config,
        generated_at=now,
    )
    currency_report = build_quality_report(
        category=category,
        articles=[currency_number],
        quality_config=quality_config,
        generated_at=now,
    )

    assert generic_report["events"][0]["price_amount"] is None
    assert "price" in generic_report["events"][0]["required_field_gaps"]
    assert currency_report["events"][0]["price_amount"] == 17000.0
    assert "price" not in currency_report["events"][0]["required_field_gaps"]


def test_build_quality_report_marks_quiet_official_notice_sources_as_quiet() -> None:
    now = datetime(2026, 4, 14, tzinfo=UTC)
    source = Source(
        name="Spotify Newsroom",
        type="rss",
        url="https://newsroom.spotify.com/feed",
        trust_tier="T1_official",
        content_type="news",
        info_purpose=["official_news", "plan_change"],
        config={"quiet_when_no_items": True},
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )

    report = build_quality_report(
        category=category,
        articles=[],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["plan_change_notice"]},
                "freshness_sla": {"plan_change_notice": {"max_age_days": 3}},
            }
        },
        generated_at=now,
    )

    assert report["summary"]["quiet_sources"] == 1
    assert report["summary"]["missing_sources"] == 0
    assert report["summary"]["tracked_source_gap_count"] == 0
    assert report["sources"][0]["status"] == "quiet"


def test_build_quality_report_uses_source_config_plan_defaults() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    source = Source(
        name="Netflix Plans & Pricing",
        type="browser",
        url="https://www.netflix.com/pricing",
        trust_tier="T1_official",
        content_type="pricing",
        producer_role="vendor",
        info_purpose=["pricing", "billing"],
        config={
            "vendor_id": "netflix",
            "plan_id": "pricing-catalog",
            "plan_name": "Pricing catalog",
            "region": "KR",
        },
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Plans and Pricing | Netflix Help Center",
        link="https://www.netflix.com/pricing",
        summary="Netflix subscription plans start at KRW 7,000.",
        published=now,
        source="Netflix Plans & Pricing",
        category="subscription",
        matched_entities={"Provider": ["netflix"], "Price": ["pricing"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["pricing_page_snapshot"]},
                "event_models": {
                    "pricing_page_snapshot": {
                        "required_fields": [
                            "vendor_id",
                            "plan_id",
                            "price",
                            "currency",
                            "source_url",
                        ]
                    }
                },
            }
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["plan_id"] == "pricing-catalog"
    assert event["plan_name"] == "Pricing catalog"
    assert event["canonical_key"] == "subscription_plan:netflix:pricing-catalog:kr:krw"
    assert event["canonical_key_status"] == "complete"
    assert event["required_field_gaps"] == []


def test_build_quality_report_infers_arr_metric_value_for_churn_proxy() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    source = Source(
        name="The SaaS Podcast",
        type="rss",
        url="https://saasclub.io/feed/podcast/",
        info_purpose=["churn_proxy"],
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="The Risky AI SaaS Rebuild That Broke a $2M ARR Ceiling",
        link="https://example.com/arr",
        summary="AI SaaS founder story with 24-25% free trial conversion.",
        published=now,
        source="The SaaS Podcast",
        category="subscription",
        matched_entities={"Provider": ["chatgpt"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["churn_proxy"]},
                "event_models": {
                    "churn_proxy": {
                        "required_fields": [
                            "vendor_id",
                            "metric_name",
                            "metric_value",
                            "source",
                        ]
                    }
                },
            }
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["metric_name"] == "arr"
    assert event["metric_value"] == 2_000_000.0
    assert event["required_field_gaps"] == []


def test_build_quality_report_infers_sales_share_percentage_for_churn_proxy() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    source = Source(
        name="Subscription Insider",
        type="rss",
        url="https://www.subscriptioninsider.com/feed/",
        info_purpose=["churn_proxy"],
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Chewy’s Autoship Customer Sales Reached 83.3% of Net Sales in Fiscal 2025",
        link="https://example.com/sales-share",
        summary="Subscription signal from autoship.",
        published=now,
        source="Subscription Insider",
        category="subscription",
        matched_entities={"Provider": ["chewy"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["churn_proxy"]},
                "event_models": {
                    "churn_proxy": {
                        "required_fields": [
                            "vendor_id",
                            "metric_name",
                            "metric_value",
                            "source",
                        ]
                    }
                },
            }
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["metric_name"] == "sales_share_percent"
    assert event["metric_value"] == 83.3
    assert event["required_field_gaps"] == []


def test_build_quality_report_prefers_growth_percentage_over_weak_price_point() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    source = Source(
        name="The SaaS Podcast",
        type="rss",
        url="https://saasclub.io/feed/podcast/",
        info_purpose=["churn_proxy"],
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="Bootstrapped SaaS Growth When AI Took Over the Market",
        link="https://example.com/growth",
        summary=(
            "The company is growing 60% year over year. "
            "Earlier pricing experiments dropped from $49 to $9."
        ),
        published=now,
        source="The SaaS Podcast",
        category="subscription",
        matched_entities={"Provider": ["parseur"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["churn_proxy"]},
                "event_models": {
                    "churn_proxy": {
                        "required_fields": [
                            "vendor_id",
                            "metric_name",
                            "metric_value",
                            "source",
                        ]
                    }
                },
            }
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["metric_name"] == "growth_rate_percent"
    assert event["metric_value"] == 60.0


def test_build_quality_report_extracts_app_store_ranking_fields() -> None:
    now = datetime(2026, 4, 21, tzinfo=UTC)
    source = Source(
        name="Apple App Store Top Free US",
        type="json",
        url="https://rss.applemarketingtools.com/api/v2/us/apps/top-free/25/apps.json",
        trust_tier="T1_official",
        content_type="ranking",
        producer_role="marketplace",
        info_purpose=["app_store_ranking"],
        config={"market": "US", "category": "top_free_apps"},
    )
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[source],
        entities=[],
    )
    article = Article(
        title="ChatGPT ranks #1 in US App Store Top Free Apps",
        link="https://apps.apple.com/us/app/chatgpt/id6448311069",
        summary=(
            "Vendor: OpenAI OpCo, LLC. App ID: 6448311069. "
            "Rank: 1. Market: US. Category: top_free_apps. "
            "Source URL: https://apps.apple.com/us/app/chatgpt/id6448311069."
        ),
        published=now,
        source="Apple App Store Top Free US",
        category="subscription",
        matched_entities={"Provider": ["chatgpt"]},
    )

    report = build_quality_report(
        category=category,
        articles=[article],
        quality_config={
            "data_quality": {
                "quality_outputs": {"tracked_event_models": ["app_store_ranking"]},
                "event_models": {
                    "app_store_ranking": {
                        "required_fields": ["app_id", "rank", "market", "category"]
                    }
                },
            }
        },
        generated_at=now,
    )

    event = report["events"][0]
    assert event["event_model"] == "app_store_ranking"
    assert event["app_id"] == "6448311069"
    assert event["rank"] == 1
    assert event["market"] == "US"
    assert event["app_category"] == "top_free_apps"
    assert event["canonical_key"] == "app_store:us:top_free_apps:6448311069"
    assert event["canonical_key_status"] == "complete"
    assert event["required_field_gaps"] == []
    assert report["summary"]["app_store_ranking_events"] == 1
    assert report["summary"]["missing_event_model_count"] == 0
