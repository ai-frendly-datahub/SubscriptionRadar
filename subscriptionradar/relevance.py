from __future__ import annotations

from collections.abc import Iterable

from .models import Article, Source


CONTEXT_PURPOSES = {
    "app_store_ranking",
    "billing",
    "bundle",
    "cancellation",
    "churn_proxy",
    "plan_change",
    "pricing",
    "pricing_page_snapshot",
    "promotion",
}
OPERATIONAL_CONTENT_TYPES = {"notice", "pricing"}
SPECIALIST_SOURCE_NAMES = {
    "openview blog",
    "saas mag",
    "saastr",
    "subscription economy news",
    "subscription insider",
    "the saas podcast",
}
RELEVANT_COMMUNITY_SOURCE_NAMES = {
    "r/applemusic",
    "r/cordcutters",
    "r/saas",
    "r/spotify",
    "r/streaming",
}
STRONG_ENTITY_NAMES = {"BillingPolicy", "PlanChange"}
INVALID_PAGE_TERMS = {
    "404",
    "access denied",
    "not found",
    "page not found",
    "request blocked",
    "service unavailable",
    "일시적인 문제가 발생했습니다",
    "페이지를 찾을 수 없습니다",
}
SUBSCRIPTION_HINT_TERMS = {
    "ad-supported",
    "annual",
    "billing",
    "bundle",
    "cancel",
    "cancellation",
    "churn",
    "discount",
    "family plan",
    "membership",
    "monthly",
    "plan",
    "premium",
    "price",
    "pricing",
    "renewal",
    "subscription",
    "tier",
    "trial",
    "요금",
    "요금제",
    "월간",
    "연간",
    "유료",
    "정기결제",
    "청구",
    "프리미엄",
    "해지",
}
PRECISE_SUBSCRIPTION_TERMS = {
    "$",
    "/month",
    "a month",
    "ad-supported",
    "annual plan",
    "billing",
    "cancel",
    "cancellation",
    "churn",
    "coupon",
    "family plan",
    "free trial",
    "membership",
    "monthly",
    "per month",
    "price",
    "premium plan",
    "price hike",
    "price increase",
    "pricing",
    "promo code",
    "renewal",
    "subscription",
    "tier",
    "요금",
    "요금제",
    "월간",
    "연간",
    "정기결제",
    "청구",
    "해지",
}


def apply_source_context_entities(
    articles: Iterable[Article],
    sources: Iterable[Source],
) -> list[Article]:
    source_map = {source.name: source for source in sources if source.enabled}
    classified: list[Article] = []
    for article in articles:
        source = source_map.get(article.source)
        if source is not None:
            tags = _source_context_tags(source)
            if tags:
                existing = article.matched_entities.get("SourceSignal", [])
                merged = sorted({str(value) for value in existing} | set(tags))
                article.matched_entities["SourceSignal"] = merged
        classified.append(article)
    return classified


def filter_relevant_articles(
    articles: Iterable[Article],
    sources: Iterable[Source],
) -> list[Article]:
    source_map = {source.name: source for source in sources if source.enabled}
    filtered: list[Article] = []
    for article in articles:
        if article.category != "subscription":
            filtered.append(article)
            continue

        source = source_map.get(article.source)
        if source is None or _is_invalid_page(article):
            continue
        if _is_app_store_ranking_source(source):
            if _has_relevant_app_store_ranking_signal(article):
                filtered.append(article)
            continue
        if _is_operational_source(source) or _has_strong_subscription_signal(article, source):
            filtered.append(article)
    return filtered


def _has_strong_subscription_signal(article: Article, source: Source) -> bool:
    haystack = f"{article.title} {article.summary}".lower()
    entities = set(article.matched_entities)
    source_name = source.name.lower()
    precise_signal = _has_precise_subscription_terms(haystack)

    if source_name.startswith("r/") and source_name not in RELEVANT_COMMUNITY_SOURCE_NAMES:
        return False

    if source_name in RELEVANT_COMMUNITY_SOURCE_NAMES:
        if "BillingPolicy" in entities or ("PlanChange" in entities and precise_signal):
            return True
        if "Price" in entities and ("Subscription" in entities or "Provider" in entities):
            return precise_signal
        if "Subscription" in entities or "ServiceType" in entities:
            return precise_signal
        return False

    if "BillingPolicy" in entities:
        return True

    if "PlanChange" in entities and precise_signal:
        return True

    if "Price" in entities and ("Subscription" in entities or "Provider" in entities):
        return precise_signal

    if "Subscription" in entities and ("Provider" in entities or "ServiceType" in entities):
        return precise_signal

    if source_name in SPECIALIST_SOURCE_NAMES:
        return precise_signal or "ServiceType" in entities

    return False


def _is_invalid_page(article: Article) -> bool:
    title = (article.title or "").strip().lower()
    summary = (article.summary or "").strip().lower()
    return any(term in title or term in summary for term in INVALID_PAGE_TERMS)


def _is_operational_source(source: Source) -> bool:
    content_type = source.content_type.lower()
    if content_type in OPERATIONAL_CONTENT_TYPES:
        return True
    return False


def _is_app_store_ranking_source(source: Source) -> bool:
    if str(source.config.get("event_model") or "").strip() == "app_store_ranking":
        return True
    return "app_store_ranking" in source.info_purpose


def _has_relevant_app_store_ranking_signal(article: Article) -> bool:
    entities = set(article.matched_entities)
    if "Provider" in entities:
        return True
    if "Subscription" in entities and ("Service" in entities or "ServiceType" in entities):
        return True
    return False


def _source_context_tags(source: Source) -> list[str]:
    tags = {tag for tag in source.info_purpose if tag in CONTEXT_PURPOSES}
    content_type = source.content_type.lower()
    source_name = source.name.lower()

    raw_model = source.config.get("event_model")
    if isinstance(raw_model, str) and raw_model.strip():
        tags.add(raw_model.strip())
    if content_type in OPERATIONAL_CONTENT_TYPES:
        tags.add(content_type)
    if source_name in SPECIALIST_SOURCE_NAMES:
        tags.add("churn_proxy")
    if source_name in RELEVANT_COMMUNITY_SOURCE_NAMES or content_type == "community":
        tags.add("community")
    return sorted(tags)


def _has_precise_subscription_terms(haystack: str) -> bool:
    return any(term in haystack for term in PRECISE_SUBSCRIPTION_TERMS)
