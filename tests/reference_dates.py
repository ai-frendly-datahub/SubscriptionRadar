"""Fixed clock for date assertions. Tests must not depend on the wall clock."""

from datetime import UTC, datetime


REFERENCE_NOW = datetime(2026, 3, 13, 12, 0, tzinfo=UTC)
