from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from subscriptionradar.models import Article, CategoryConfig, EntityDefinition, Source
from subscriptionradar.storage import RadarStorage


@pytest.fixture
def tmp_storage(tmp_path: Path) -> RadarStorage:
    """Create a temporary RadarStorage instance for testing."""
    db_path = tmp_path / "test.duckdb"
    storage = RadarStorage(db_path)
    yield storage
    storage.close()


@pytest.fixture
def sample_articles() -> list[Article]:
    """Create sample articles with realistic 구독 domain data."""
    now = datetime.now(UTC)
    return [
        Article(
            title="Netflix 요금 인상 안내",
            link="https://subscription.example.com/netflix-2024",
            summary="Netflix 구독료가 인상되었습니다.",
            published=now,
            source="subscriptionradar_api",
            category="subscription",
            matched_entities={},
        ),
        Article(
            title="Spotify 프리미엄 가격 변경",
            link="https://subscription.example.com/spotify-2024",
            summary="Spotify 프리미엄 요금이 변경되었습니다.",
            published=now,
            source="subscriptionradar_api",
            category="subscription",
            matched_entities={},
        ),
        Article(
            title="클라우드 스토리지 구독 비교",
            link="https://subscription.example.com/cloud-2024",
            summary="주요 클라우드 서비스 구독료 비교입니다.",
            published=now,
            source="subscriptionradar_api",
            category="subscription",
            matched_entities={},
        ),
        Article(
            title="게임 구독 서비스 출시",
            link="https://subscription.example.com/gaming-2024",
            summary="새로운 게임 구독 서비스가 출시되었습니다.",
            published=now,
            source="subscriptionradar_api",
            category="subscription",
            matched_entities={},
        ),
        Article(
            title="OTT 서비스 프로모션",
            link="https://subscription.example.com/ott-2024",
            summary="OTT 서비스 할인 프로모션 정보입니다.",
            published=now,
            source="subscriptionradar_api",
            category="subscription",
            matched_entities={},
        ),
    ]


@pytest.fixture
def sample_entities() -> list[EntityDefinition]:
    """Create sample entities with 구독 domain keywords."""
    return [
        EntityDefinition(
            name="video_streaming",
            display_name="영상 스트리밍",
            keywords=["Netflix", "OTT", "영상", "스트리밍"],
        ),
        EntityDefinition(
            name="music_streaming",
            display_name="음악 스트리밍",
            keywords=["Spotify", "음악", "스트리밍", "구독"],
        ),
        EntityDefinition(
            name="cloud_storage",
            display_name="클라우드 스토리지",
            keywords=["클라우드", "스토리지", "저장소", "구독"],
        ),
        EntityDefinition(
            name="gaming_subscription",
            display_name="게임 구독",
            keywords=["게임", "구독", "서비스", "플레이"],
        ),
        EntityDefinition(
            name="membership",
            display_name="멤버십",
            keywords=["멤버십", "구독", "정기결제", "프리미엄"],
        ),
    ]


@pytest.fixture
def sample_config(tmp_path: Path, sample_entities: list[EntityDefinition]) -> CategoryConfig:
    """Create a sample CategoryConfig for testing."""
    sources = [
        Source(
            name="subscriptionradar_api",
            type="api",
            url="https://api.subscriptionradar.example.com",
        ),
    ]
    return CategoryConfig(
        category_name="subscription",
        display_name="구독",
        sources=sources,
        entities=sample_entities,
    )
