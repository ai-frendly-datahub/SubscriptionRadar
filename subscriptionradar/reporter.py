from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Mapping
from html import escape
from pathlib import Path
from typing import Any

from radar_core.ontology import build_summary_ontology_metadata
from radar_core.report_utils import (
    generate_index_html as _core_generate_index_html,
)
from radar_core.report_utils import (
    generate_report as _core_generate_report,
)

from .models import Article, CategoryConfig


def generate_report(
    *,
    category: CategoryConfig,
    articles: Iterable[Article],
    output_path: Path,
    stats: dict[str, int],
    errors: list[str] | None = None,
    store=None,
    quality_report: Mapping[str, Any] | None = None,
) -> Path:
    """Generate HTML report (delegates to radar-core)."""
    articles_list = list(articles)
    plugin_charts = []
    extra_sections: list[dict[str, Any]] = []

    # --- Universal plugins (entity heatmap + source reliability) ---
    try:
        from radar_core.plugins.entity_heatmap import get_chart_config as _heatmap_config

        _heatmap = _heatmap_config(articles=articles_list)
        if _heatmap is not None:
            plugin_charts.append(_heatmap)
    except Exception:
        pass
    try:
        from radar_core.plugins.source_reliability import get_chart_config as _reliability_config

        _reliability = _reliability_config(store=store)
        if _reliability is not None:
            plugin_charts.append(_reliability)
    except Exception:
        pass

    if quality_report:
        extra_sections.append(_build_subscription_quality_section(quality_report))
    return _core_generate_report(
        category=category,
        articles=articles_list,
        output_path=output_path,
        stats=stats,
        errors=errors,
        plugin_charts=plugin_charts if plugin_charts else None,
        extra_sections=extra_sections or None,
        ontology_metadata=build_summary_ontology_metadata(
            "SubscriptionRadar",
            category_name=category.category_name,
            search_from=Path(__file__).resolve(),
        ),
    )


def generate_index_html(
    report_dir: Path,
    summaries_dir: Path | None = None,
) -> Path:
    """Generate index.html (delegates to radar-core)."""
    radar_name = "Subscription Radar"
    return _core_generate_index_html(report_dir, radar_name)


def _build_subscription_quality_section(
    quality_report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "id": "subscription-quality",
        "title": "Subscription Quality",
        "panel_title": "Pricing and Plan Signal Coverage",
        "subtitle": "Pricing, plan-change, ranking, and churn-proxy evidence from the latest contract.",
        "badges": ["subscription_quality.json", "pricing", "review"],
        "body_html": _render_subscription_quality_body(quality_report),
    }


def _render_subscription_quality_body(quality_report: Mapping[str, Any]) -> str:
    summary = _mapping(quality_report.get("summary"))
    chips = [
        ("Events", summary.get("subscription_signal_event_count", 0)),
        ("Pricing", summary.get("pricing_page_snapshot_events", 0)),
        ("Plan keys", summary.get("plan_canonical_key_present_count", 0)),
        ("Vendor proxy", summary.get("vendor_proxy_key_count", 0)),
        ("Price", summary.get("price_amount_present_count", 0)),
        ("Field gaps", summary.get("event_required_field_gap_count", 0)),
        ("Review", summary.get("daily_review_item_count", 0)),
    ]
    chip_html = "\n".join(
        "<div class=\"metric-card\">"
        f"<span>{escape(label)}</span><strong>{escape(str(value))}</strong>"
        "</div>"
        for label, value in chips
    )
    events_html = _render_quality_events(_list_of_mappings(quality_report.get("events"))[:8])
    review_html = _render_quality_review(
        _list_of_mappings(quality_report.get("daily_review_items"))[:8]
    )
    return (
        f"<div class=\"metric-grid\">{chip_html}</div>"
        "<p>Tracked subscription events and daily review items are rendered inside the shared report shell.</p>"
        "<div>"
        "<h3>Tracked Events</h3>"
        f"{events_html}"
        "</div>"
        "<div>"
        "<h3>Daily Review</h3>"
        f"{review_html}"
        "</div>"
    )


def _render_quality_events(events: list[Mapping[str, Any]]) -> str:
    if not events:
        return "<p>No tracked subscription quality events were generated.</p>"
    rows = []
    for event in events:
        price = event.get("price_amount")
        if price is None:
            price_text = ""
        else:
            price_text = str(price)
        rows.append(
            "<tr>"
            f"<td>{escape(str(event.get('event_model') or ''))}</td>"
            f"<td>{escape(str(event.get('source') or ''))}</td>"
            f"<td>{escape(str(event.get('vendor_name') or event.get('vendor_id') or ''))}</td>"
            f"<td>{escape(str(event.get('plan_name') or event.get('plan_id') or ''))}</td>"
            f"<td>{escape(price_text)} {escape(str(event.get('currency') or ''))}</td>"
            f"<td><code>{escape(str(event.get('canonical_key') or ''))}</code></td>"
            "</tr>"
        )
    return (
        "<div style=\"overflow-x:auto;\">"
        "<table class=\"data-table\">"
        "<thead><tr><th>Model</th><th>Source</th><th>Vendor</th><th>Plan</th><th>Price</th><th>Canonical Key</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody>"
        "</table>"
        "</div>"
    )


def _render_quality_review(items: list[Mapping[str, Any]]) -> str:
    if not items:
        return "<p>No subscription quality review items.</p>"
    rendered = []
    for item in items:
        reason = escape(str(item.get("reason") or "review"))
        source = escape(str(item.get("source") or item.get("event_model") or ""))
        detail = escape(
            str(item.get("canonical_key") or item.get("activation_gate") or item.get("title") or "")
        )
        rendered.append(f"<li><strong>{reason}</strong> {source} <span>{detail}</span></li>")
    return f"<ul class=\"review-list\">{''.join(rendered)}</ul>"


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _list_of_mappings(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]
