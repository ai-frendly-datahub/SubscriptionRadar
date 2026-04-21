from __future__ import annotations

from subscriptionradar.config_loader import load_category_config, load_category_quality_config


def test_load_category_config_preserves_source_metadata(tmp_path) -> None:
    categories_dir = tmp_path / "categories"
    categories_dir.mkdir()
    (categories_dir / "subscription.yaml").write_text(
        """
category_name: subscription
display_name: Subscription
sources:
  - name: Notion Pricing
    id: notion_pricing
    type: browser
    url: https://www.notion.com/pricing
    enabled: true
    trust_tier: T1_official
    weight: 2.0
    content_type: pricing
    collection_tier: C3_html_js
    producer_role: vendor
    info_purpose:
      - pricing
      - plan_change
    notes: official pricing page
    config:
      wait_for: body
entities: []
""",
        encoding="utf-8",
    )

    config = load_category_config("subscription", categories_dir=categories_dir)
    source = config.sources[0]

    assert source.id == "notion_pricing"
    assert source.enabled is True
    assert source.trust_tier == "T1_official"
    assert source.weight == 2.0
    assert source.content_type == "pricing"
    assert source.collection_tier == "C3_html_js"
    assert source.producer_role == "vendor"
    assert source.info_purpose == ["pricing", "plan_change"]
    assert source.notes == "official pricing page"
    assert source.config == {"wait_for": "body"}


def test_load_category_quality_config_returns_quality_contract(tmp_path) -> None:
    categories_dir = tmp_path / "categories"
    categories_dir.mkdir()
    (categories_dir / "subscription.yaml").write_text(
        """
category_name: subscription
data_quality:
  quality_outputs:
    tracked_event_models:
      - pricing_page_snapshot
source_backlog:
  operational_candidates:
    - id: pricing_page_diff_store
sources: []
entities: []
""",
        encoding="utf-8",
    )

    quality = load_category_quality_config("subscription", categories_dir=categories_dir)

    assert quality["data_quality"] == {
        "quality_outputs": {"tracked_event_models": ["pricing_page_snapshot"]}
    }
    assert quality["source_backlog"] == {
        "operational_candidates": [{"id": "pricing_page_diff_store"}]
    }
