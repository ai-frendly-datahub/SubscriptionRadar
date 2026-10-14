from __future__ import annotations

# Re-export from radar-core shared package
from radar_core.exceptions import (
    CollectionError,
    ConfigError,
    NetworkError,
    NotificationError,
    ParseError,
    RadarError,
    ReportError,
    SearchError,
    SourceError,
    StorageError,
)


class EmptyCollectionError(CollectionError):
    """Enabled sources produced no articles. An empty run is not success."""


__all__ = [
    "CollectionError",
    "ConfigError",
    "EmptyCollectionError",
    "NetworkError",
    "NotificationError",
    "ParseError",
    "RadarError",
    "ReportError",
    "SearchError",
    "SourceError",
    "StorageError",
]
