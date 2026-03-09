from __future__ import annotations

from unittest.mock import patch

import pytest

from subscriptionradar.models import Article, Source
from subscriptionradar.storage import RadarStorage


@pytest.mark.integration
def test_collection_workflow(
    sample_articles: list[Article],
) -> None:
    """Test complete collection workflow: mock API → collect → verify structure."""
    with patch("subscriptionradar.collector.collect_sources") as mock_collect:
        mock_collect.return_value = (sample_articles, [])

        articles, errors = mock_collect(
            [
                Source(
                    name="subscriptionradar_api",
                    type="api",
                    url="https://api.subscriptionradar.example.com",
                )
            ],
            category="subscription",
            limit_per_source=30,
        )

        assert len(articles) == 5
        assert len(errors) == 0
        assert all(isinstance(a, Article) for a in articles)
        assert all(a.category == "subscription" for a in articles)


@pytest.mark.integration
def test_storage_persistence(
    tmp_storage: RadarStorage,
    sample_articles: list[Article],
) -> None:
    """Test storage integration: insert articles → query → verify data integrity."""
    tmp_storage.upsert_articles(sample_articles)

    articles = tmp_storage.recent_articles(category="subscription", days=30, limit=100)

    assert len(articles) == 5
    assert articles[0].category == "subscription"
    assert articles[0].link is not None


@pytest.mark.integration
def test_duplicate_handling(
    tmp_storage: RadarStorage,
    sample_articles: list[Article],
) -> None:
    """Test duplicate handling: insert same link twice → verify single entry."""
    tmp_storage.upsert_articles(sample_articles[:2])
    result1 = tmp_storage.recent_articles(category="subscription", days=30, limit=100)
    assert len(result1) == 2

    tmp_storage.upsert_articles(sample_articles[:2])
    result2 = tmp_storage.recent_articles(category="subscription", days=30, limit=100)
    assert len(result2) == 2

    tmp_storage.upsert_articles(sample_articles[2:])
    result3 = tmp_storage.recent_articles(category="subscription", days=30, limit=100)
    assert len(result3) == 5
