"""Tests for PolilyDB unified SQLite database layer."""

import tempfile
from pathlib import Path

from scanner.db import PolilyDB


def test_db_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        db = PolilyDB(db_path)
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(r[0] for r in tables if not r[0].startswith("sqlite_"))
        assert table_names == [
            "analyses", "market_states", "notifications", "paper_trades", "scan_logs",
        ]
        db.close()


def test_db_context_manager():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        with PolilyDB(db_path) as db:
            assert db.conn is not None


def test_db_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "nested" / "dir" / "polily.db"
        with PolilyDB(db_path) as db:
            assert db_path.exists()


def test_db_creates_indexes():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        with PolilyDB(db_path) as db:
            indexes = db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
            ).fetchall()
            index_names = sorted(r[0] for r in indexes)
            assert "idx_analyses_market" in index_names
            assert "idx_states_watch_due" in index_names
            assert "idx_notifications_unread" in index_names


def test_db_wal_mode():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        with PolilyDB(db_path) as db:
            mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
