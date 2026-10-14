from __future__ import annotations

import importlib
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path

import pytest
import structlog

from tests.reference_dates import REFERENCE_NOW


class FrozenDateTime(datetime):
    """datetime.now() in date-stamping modules returns REFERENCE_NOW."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        if tz is None:
            return REFERENCE_NOW.replace(tzinfo=None)
        return REFERENCE_NOW


@pytest.fixture(autouse=True)
def freeze_reference_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    for module_name in ("subscriptionradar.date_storage", "subscriptionradar.raw_logger"):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "datetime", FrozenDateTime)


@pytest.fixture(autouse=True)
def reset_structlog() -> object:
    structlog.reset_defaults()
    yield
    structlog.reset_defaults()


@pytest.fixture(autouse=True)
def isolate_crawl_health_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RADAR_CRAWL_HEALTH_DB_PATH", str(tmp_path / "crawl_health.duckdb"))


@pytest.fixture
def sample_source() -> object:
    from subscriptionradar.models import Source

    return Source(name="Example RSS", type="rss", url="https://example.com/feed.xml")


@pytest.fixture
def sample_entity() -> object:
    from subscriptionradar.models import EntityDefinition

    return EntityDefinition(name="topic", display_name="Topic", keywords=["ai", "cloud", "python"])


@pytest.fixture
def sample_article() -> object:
    from subscriptionradar.models import Article

    return Article(
        title="AI and cloud market update",
        link="https://example.com/article-1",
        summary="Python tooling and AI adoption continue to grow.",
        published=datetime.now(UTC) - timedelta(days=1),
        source="Example RSS",
        category="tech",
        matched_entities={"topic": ["ai", "cloud", "python"]},
    )


@pytest.fixture
def tmp_duckdb(tmp_path: Path) -> Path:
    return tmp_path / "test_radar_data.duckdb"


@pytest.fixture
def tmp_search_db(tmp_path: Path) -> Path:
    return tmp_path / "test_search_index.db"


@pytest.fixture
def tmp_storage(tmp_duckdb: Path) -> object:
    from subscriptionradar.storage import RadarStorage

    storage = RadarStorage(tmp_duckdb)
    try:
        yield storage
    finally:
        storage.close()


@pytest.fixture
def tmp_search_index(tmp_search_db: Path) -> object:
    from subscriptionradar.search_index import SearchIndex

    index = SearchIndex(tmp_search_db)
    try:
        yield index
    finally:
        index.close()
