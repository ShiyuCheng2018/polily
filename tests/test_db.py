"""Tests for PolilyDB unified SQLite database layer."""

import tempfile
from pathlib import Path

import pytest

from polily.core.db import PolilyDB


@pytest.fixture
def polily_db():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        db = PolilyDB(db_path)
        yield db
        db.close()


def test_v2_schema_tables(polily_db):
    """v2 schema should have the expected core tables (and no retired ones)."""
    tables = polily_db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    names = [t[0] for t in tables]
    assert "events" in names
    assert "markets" in names
    assert "event_monitors" in names
    assert "analyses" in names
    assert "movement_log" in names
    assert "scan_logs" in names
    assert "market_states" not in names
    # paper_trades dropped in v0.6.1 (replaced by positions + wallet_transactions)
    assert "paper_trades" not in names
    # notifications dropped post-v0.6.1 (replaced by archive view over wallet_transactions)
    assert "notifications" not in names


def test_events_table_columns(polily_db):
    row = polily_db.conn.execute("PRAGMA table_info(events)").fetchall()
    cols = {r[1] for r in row}
    assert "event_id" in cols
    assert "structure_score" in cols
    assert "tier" in cols
    assert "user_status" in cols
    assert "neg_risk" in cols
    assert "neg_risk_market_id" in cols
    assert "neg_risk_augmented" in cols
    assert "market_type" in cols
    assert "event_metadata" in cols


def test_markets_table_columns(polily_db):
    row = polily_db.conn.execute("PRAGMA table_info(markets)").fetchall()
    cols = {r[1] for r in row}
    assert "market_id" in cols
    assert "event_id" in cols
    assert "question" in cols
    assert "group_item_title" in cols
    assert "group_item_threshold" in cols
    assert "condition_id" in cols
    assert "clob_token_id_yes" in cols
    assert "clob_token_id_no" in cols
    assert "neg_risk" in cols
    assert "neg_risk_request_id" in cols
    assert "neg_risk_other" in cols
    assert "book_bids" in cols
    assert "book_asks" in cols
    assert "recent_trades" in cols
    assert "bid_depth" in cols
    assert "ask_depth" in cols
    assert "structure_score" in cols
    assert "yes_price" in cols
    assert "best_bid" in cols
    assert "accepting_orders" in cols
    assert "order_min_tick_size" in cols


def test_event_monitors_columns(polily_db):
    row = polily_db.conn.execute("PRAGMA table_info(event_monitors)").fetchall()
    cols = {r[1] for r in row}
    assert "event_id" in cols
    assert "auto_monitor" in cols
    assert "price_snapshot" in cols
    assert "notes" in cols
    assert "poll_interval_s" not in cols
    # v0.7.0 Task 1: scheduling moved to scan_logs pending rows.
    assert "next_check_at" not in cols
    assert "next_check_reason" not in cols


def test_analyses_uses_event_id(polily_db):
    row = polily_db.conn.execute("PRAGMA table_info(analyses)").fetchall()
    cols = {r[1] for r in row}
    assert "event_id" in cols
    assert "market_id" not in cols
    assert "prices_snapshot" in cols
    assert "narrative_output" in cols


def test_movement_log_has_event_id(polily_db):
    row = polily_db.conn.execute("PRAGMA table_info(movement_log)").fetchall()
    cols = {r[1] for r in row}
    assert "event_id" in cols
    assert "no_price" in cols


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


def test_db_wal_mode():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "polily.db"
        with PolilyDB(db_path) as db:
            mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode == "wal"


def test_upgrade_drops_legacy_notifications_table(tmp_path):
    """Existing databases with a `notifications` table get it dropped on
    next PolilyDB open — guards the post-v0.6.1 migration from Task 8 of
    the archive-view refactor.
    """
    import sqlite3

    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE notifications (id INTEGER PRIMARY KEY, foo TEXT)")
    conn.commit()
    conn.close()

    db = PolilyDB(db_path)
    try:
        tables = {
            r[0] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "notifications" not in tables
    finally:
        db.close()
