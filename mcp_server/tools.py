from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import duckdb

from subscriptionradar.nl_query import parse_query
from subscriptionradar.search_index import SearchIndex


_ALLOWED_SQL = re.compile(r"^\s*(SELECT|WITH|EXPLAIN)\b", re.IGNORECASE)


def _filter_links_by_days(*, db_path: Path, links: list[str], days: int) -> set[str]:
    if not links:
        return set()
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            "SELECT link FROM articles WHERE collected_at >= ?",
            [cutoff],
        ).fetchall()
    recent_links = {str(row[0]) for row in rows}
    return {link for link in links if link in recent_links}


def handle_search(*, search_db_path: Path, db_path: Path, query: str, limit: int = 20) -> str:
    parsed = parse_query(query)
    effective_limit = parsed.limit if parsed.limit is not None else limit
    search_text = parsed.search_text or query.strip()
    if effective_limit <= 0 or not search_text:
        return "No results found."

    with SearchIndex(search_db_path) as idx:
        results = idx.search(search_text, limit=effective_limit)
    if parsed.days is not None:
        allowed = _filter_links_by_days(
            db_path=db_path,
            links=[result.link for result in results],
            days=parsed.days,
        )
        results = [result for result in results if result.link in allowed]
    if not results:
        return "No results found."
    return "\n".join(["Found results:", *[f"- {result.title} | {result.link}" for result in results]])


def handle_recent_updates(*, db_path: Path, days: int = 7, limit: int = 20) -> str:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT title, source, link, collected_at
            FROM articles
            WHERE collected_at >= ?
            ORDER BY collected_at DESC
            LIMIT ?
            """,
            [cutoff, limit],
        ).fetchall()
    if not rows:
        return "No recent updates found."
    return "\n".join([f"- {row[0]} | {row[1]} | {row[3]} | {row[2]}" for row in rows])


def handle_sql(*, db_path: Path, query: str) -> str:
    if not _ALLOWED_SQL.match(query):
        return "Error: Only SELECT/WITH/EXPLAIN queries are allowed."
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            cursor = conn.execute(query)
            rows = cursor.fetchall()
            columns = [str(desc[0]) for desc in cursor.description] if cursor.description else []
    except Exception as exc:
        return f"Error: {exc}"
    return json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False, default=str)


def handle_top_trends(*, db_path: Path, days: int = 7, limit: int = 10) -> str:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    with duckdb.connect(str(db_path), read_only=True) as conn:
        rows = conn.execute(
            "SELECT entities_json FROM articles WHERE collected_at >= ?",
            [cutoff],
        ).fetchall()
    counts: Counter[str] = Counter()
    for (raw_entities,) in cast(list[tuple[str | None]], rows):
        if not raw_entities:
            continue
        try:
            data = json.loads(str(raw_entities))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            for entity, matched in data.items():
                counts[str(entity)] += len(matched) if isinstance(matched, list) else 1
    if not counts:
        return "No trend data available."
    return "\n".join([f"- {entity}: {count}" for entity, count in counts.most_common(limit)])


def handle_price_watch(*, threshold: float = 0.0) -> str:
    _ = threshold
    return "Not available in template project"
