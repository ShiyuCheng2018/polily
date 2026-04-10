"""Tests for auto_monitor toggle.

TODO: v0.5.0 — rewrite when auto_monitor is rebuilt for event-first schema.
Currently tests the stubbed toggle_auto_monitor (no-op).
"""

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.daemon.auto_monitor import toggle_auto_monitor


def test_toggle_auto_monitor_no_crash(tmp_path):
    """toggle_auto_monitor should not crash (currently a no-op stub)."""
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()
    toggle_auto_monitor("m1", enable=True, db=db, config=config)
    toggle_auto_monitor("m1", enable=False, db=db, config=config)
    db.close()
