"""Tests for PolilyDB unified SQLite database layer."""

import tempfile
from pathlib import Path

from scanner.core.db import PolilyDB


def test_db_creates_all_tables():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        db = PolilyDB(db_path)
        tables = db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
        table_names = sorted(r[0] for r in tables if not r[0].startswith("sqlite_"))
        assert table_names == [
            "analyses", "market_states", "movement_log", "notifications", "paper_trades", "scan_logs",
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
        with PolilyDB(db_path):
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
            assert "idx_states_monitor" in index_names
            assert "idx_notifications_unread" in index_names


def test_db_has_movement_log_table():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        db = PolilyDB(db_path)
        cols = db.conn.execute("PRAGMA table_info(movement_log)").fetchall()
        col_names = [c[1] for c in cols]
        assert "market_id" in col_names
        assert "magnitude" in col_names
        assert "quality" in col_names
        assert "label" in col_names
        assert "snapshot" in col_names
        assert "trade_volume" in col_names
        db.close()


def test_db_market_states_has_condition_id():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        db = PolilyDB(db_path)
        cols = db.conn.execute("PRAGMA table_info(market_states)").fetchall()
        col_names = [c[1] for c in cols]
        assert "condition_id" in col_names
        assert "market_type" in col_names
        assert "clob_token_id_yes" in col_names
        db.close()


def test_db_wal_mode():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        with PolilyDB(db_path) as db:
            mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"
