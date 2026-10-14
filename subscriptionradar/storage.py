from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
from radar_core.exceptions import StorageError
from radar_core.storage import RadarStorage as _RadarStorage

from .date_storage import _compact_database, cleanup_date_directories, snapshot_database


class RadarStorage(_RadarStorage):
    def create_daily_snapshot(
        self,
        snapshot_dir: str | None = None,
        snapshot_date: date | None = None,
    ) -> Path | None:
        snapshot_root = Path(snapshot_dir) if snapshot_dir else self.db_path.parent / "daily"
        _ = self.conn.execute("CHECKPOINT")
        self.conn.close()
        try:
            _compact_database(self.db_path)
            return snapshot_database(
                self.db_path,
                snapshot_date=snapshot_date,
                snapshot_root=snapshot_root,
            )
        finally:
            self.conn = duckdb.connect(str(self.db_path))
            self._ensure_tables()

    def cleanup_old_snapshots(self, keep_days: int) -> int:
        return cleanup_date_directories(self.db_path.parent / "daily", keep_days=keep_days)


__all__ = ["RadarStorage", "StorageError"]
