from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DoctorContext:
    data_dir: Path
    db_path: Path
    log_dir: Path
    data_dir_tier: str          # "cli" | "env" | "default"
    launchd_label: str
    platform: str
    live: bool = False
    deep: bool = False
    offline: bool = False
    _conn: sqlite3.Connection | None = field(default=None, repr=False, init=False)
    _conn_tried: bool = field(default=False, repr=False, init=False)

    def ro_conn(self) -> sqlite3.Connection | None:
        """Lazily open a READ-ONLY connection to db_path. None if missing/unopenable."""
        if self._conn_tried:
            return self._conn
        self._conn_tried = True
        if not self.db_path.exists():
            return None
        try:
            conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout=2000")
            self._conn = conn
        except sqlite3.Error:
            self._conn = None
        return self._conn


def _resolve_tier() -> str:
    from polily.core import paths
    if paths._DATA_DIR_OVERRIDE is not None:
        return "cli"
    if os.environ.get("POLILY_DATA_DIR"):
        return "env"
    return "default"


def build_context(
    *, live: bool = False, deep: bool = False, offline: bool = False,
    platform: str | None = None,
) -> DoctorContext:
    from polily.core import paths
    return DoctorContext(
        data_dir=paths.data_dir(),
        db_path=paths.db_path(),
        log_dir=paths.log_dir(),
        data_dir_tier=_resolve_tier(),
        launchd_label=paths.launchd_label(),
        platform=platform or sys.platform,
        live=live, deep=deep, offline=offline,
    )
