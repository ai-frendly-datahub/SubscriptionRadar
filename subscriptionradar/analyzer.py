from __future__ import annotations

from collections.abc import Iterable

from radar_core.common.korean_analyzer import KoreanAnalyzer

from .models import Article, EntityDefinition


_korean_analyzer = KoreanAnalyzer()


def _is_ascii_word(keyword: str) -> bool:
    return keyword.isascii() and keyword.replace("_", "").replace("-", "").isalnum()


def _contains_keyword(text_lower: str, keyword_lower: str) -> bool:
    if not keyword_lower:
        return False
    if _is_ascii_word(keyword_lower):
        import re

        return re.search(rf"(?<![a-z0-9]){re.escape(keyword_lower)}(?![a-z0-9])", text_lower) is not None
    if keyword_lower.isascii():
        return keyword_lower in text_lower
    if _korean_analyzer._kiwi is not None:
        return _korean_analyzer.match_keyword(text_lower, keyword_lower)
    return keyword_lower in text_lower


def apply_entity_rules(
    articles: Iterable[Article],
    entities: list[EntityDefinition],
) -> list[Article]:
    analyzed: list[Article] = []
    for article in articles:
        text_lower = f"{article.title} {article.summary}".lower()
        matched: dict[str, list[str]] = {}
        for entity in entities:
            keywords = [
                keyword.lower()
                for keyword in entity.keywords
                if _contains_keyword(text_lower, keyword.lower())
            ]
            if keywords:
                matched[entity.name] = keywords
        article.matched_entities = matched
        analyzed.append(article)
    return analyzed


__all__ = ["apply_entity_rules"]
