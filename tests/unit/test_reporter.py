from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from subscriptionradar.models import Article, CategoryConfig, Source
from subscriptionradar.reporter import generate_report


pytestmark = pytest.mark.unit


def test_report_includes_subscription_quality_panel(tmp_path: Path) -> None:
    output_path = tmp_path / "subscription_report.html"
    category = CategoryConfig(
        category_name="subscription",
        display_name="Subscription",
        sources=[
            Source(
                name="Notion Pricing",
                type="browser",
                url="https://www.notion.com/pricing",
            )
        ],
        entities=[],
    )
    article = Article(
        title="Notion Pricing",
        link="https://www.notion.com/pricing",
        summary="Vendor: Notion. Plan: Plus. Price: $10. Currency: USD.",
        published=datetime(2026, 4, 14, tzinfo=UTC),
        source="Notion Pricing",
        category="subscription",
    )
    quality_report = {
        "summary": {
            "subscription_signal_event_count": 1,
            "pricing_page_snapshot_events": 1,
            "plan_canonical_key_present_count": 1,
            "vendor_proxy_key_count": 0,
            "price_amount_present_count": 1,
            "event_required_field_gap_count": 1,
            "daily_review_item_count": 1,
        },
        "events": [
            {
                "event_model": "pricing_page_snapshot",
                "source": "Notion Pricing",
                "vendor_name": "Notion",
                "plan_name": "Plus",
                "price_amount": 10.0,
                "currency": "USD",
                "canonical_key": "subscription_plan:notion:plus:us:usd",
            }
        ],
        "daily_review_items": [
            {
                "reason": "missing_required_fields",
                "source": "Netflix Plans & Pricing",
                "canonical_key": "subscription_plan:netflix",
            }
        ],
    }

    result = generate_report(
        category=category,
        articles=[article],
        output_path=output_path,
        stats={"sources": 1, "collected": 1, "matched": 1, "window_days": 7},
        quality_report=quality_report,
    )

    html = result.read_text(encoding="utf-8")
    assert "Subscription Quality" in html
    assert "pricing_page_snapshot" in html
    assert "subscription_plan:notion:plus:us:usd" in html
    assert "missing_required_fields" in html

    dated_html = next(
        tmp_path.glob("subscription_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].html")
    )
    dated_text = dated_html.read_text(encoding="utf-8")
    assert "Subscription Quality" in dated_text
    assert "subscription_plan:notion:plus:us:usd" in dated_text

    summaries = sorted(
        tmp_path.glob("subscription_[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]_summary.json")
    )
    assert len(summaries) == 1
    summary = summaries[0].read_text(encoding="utf-8")
    assert '"repo": "SubscriptionRadar"' in summary
    assert '"ontology_version": "0.1.0"' in summary
    assert '"subscription.pricing_page_snapshot"' in summary
