"""v0.7.0 migration: scan_logs CHECK extension + event_monitors column drop."""
import sqlite3
from pathlib import Path

from polily.core.db import PolilyDB


def _make_v06_db(tmp_path: Path) -> Path:
    """Create a DB in v0.6.x shape (old scan_logs CHECK, event_monitors with next_check_at)."""
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            updated_at TEXT NOT NULL, closed INTEGER DEFAULT 0,
            tier TEXT
        );
        CREATE TABLE event_monitors (
            event_id TEXT PRIMARY KEY REFERENCES events(event_id),
            auto_monitor INTEGER NOT NULL DEFAULT 0,
            next_check_at TEXT,
            next_check_reason TEXT,
            price_snapshot TEXT,
            notes TEXT DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE scan_logs (
            scan_id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'scan' CHECK(type IN ('scan','analyze','add_event')),
            event_id TEXT,
            market_title TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_elapsed REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'running'
                CHECK(status IN ('running','completed','failed')),
            error TEXT,
            total_markets INTEGER NOT NULL DEFAULT 0,
            research_count INTEGER NOT NULL DEFAULT 0,
            watchlist_count INTEGER NOT NULL DEFAULT 0,
            filtered_count INTEGER NOT NULL DEFAULT 0,
            steps TEXT
        );
        INSERT INTO events(event_id, title, updated_at) VALUES ('ev1', 'Iran', 'now');
        INSERT INTO event_monitors(event_id, auto_monitor, next_check_at, next_check_reason, updated_at)
            VALUES ('ev1', 1, '2026-05-01T10:00:00+00:00', '重要节点', 'now');
        INSERT INTO scan_logs(scan_id, type, event_id, started_at, status)
            VALUES ('s1', 'analyze', 'ev1', '2026-04-10T00:00:00+00:00', 'completed');
    """)
    conn.commit()
    conn.close()
    return db_path


def test_migration_from_v06_preserves_scan_log_rows(tmp_path):
    db_path = _make_v06_db(tmp_path)
    db = PolilyDB(db_path)
    try:
        # Filter out pending rows (which the migration seeds from event_monitors);
        # this test only asserts the pre-existing rows survive the rebuild.
        rows = db.conn.execute(
            "SELECT scan_id, status FROM scan_logs WHERE status != 'pending' ORDER BY scan_id"
        ).fetchall()
        assert [(r["scan_id"], r["status"]) for r in rows] == [("s1", "completed")]
    finally:
        db.close()


def test_migration_adds_new_columns_to_scan_logs(tmp_path):
    db_path = _make_v06_db(tmp_path)
    db = PolilyDB(db_path)
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(scan_logs)").fetchall()}
        assert "scheduled_at" in cols
        assert "trigger_source" in cols
        assert "scheduled_reason" in cols
    finally:
        db.close()


def test_migration_extends_status_check(tmp_path):
    db_path = _make_v06_db(tmp_path)
    db = PolilyDB(db_path)
    try:
        db.conn.execute(
            "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, "
            "trigger_source, scheduled_at) "
            "VALUES ('p1', 'analyze', 'ev1', '2026-05-01T10:00:00+00:00', 'pending', "
            "'scheduled', '2026-05-01T10:00:00+00:00')"
        )
        db.conn.commit()
        row = db.conn.execute("SELECT status FROM scan_logs WHERE scan_id='p1'").fetchone()
        assert row["status"] == "pending"
    finally:
        db.close()


def test_migration_moves_next_check_at_to_pending_row(tmp_path):
    db_path = _make_v06_db(tmp_path)
    db = PolilyDB(db_path)
    try:
        row = db.conn.execute(
            "SELECT event_id, status, scheduled_at, scheduled_reason, trigger_source "
            "FROM scan_logs WHERE status='pending'"
        ).fetchone()
        assert row is not None, "pending row should be seeded from event_monitors.next_check_at"
        assert row["event_id"] == "ev1"
        assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"
        assert row["scheduled_reason"] == "重要节点"
        assert row["trigger_source"] == "scheduled"
    finally:
        db.close()


def test_migration_seeds_pending_with_event_title(tmp_path):
    """Seed rows must fill market_title from events.title so the TUI 待办
    zone shows the event name instead of a '?' placeholder."""
    db_path = _make_v06_db(tmp_path)
    db = PolilyDB(db_path)
    try:
        row = db.conn.execute(
            "SELECT market_title FROM scan_logs WHERE status='pending'"
        ).fetchone()
        assert row is not None
        assert row["market_title"] == "Iran"
    finally:
        db.close()


def test_migration_drops_event_monitors_columns(tmp_path):
    db_path = _make_v06_db(tmp_path)
    db = PolilyDB(db_path)
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(event_monitors)").fetchall()}
        assert "next_check_at" not in cols
        assert "next_check_reason" not in cols
        assert {"event_id", "auto_monitor", "price_snapshot", "notes", "updated_at"} <= cols
    finally:
        db.close()


def test_migration_is_idempotent(tmp_path):
    db_path = _make_v06_db(tmp_path)
    PolilyDB(db_path).close()
    PolilyDB(db_path).close()
    db = PolilyDB(db_path)
    try:
        pending = db.conn.execute(
            "SELECT COUNT(*) FROM scan_logs WHERE status='pending'"
        ).fetchone()[0]
        assert pending == 1
    finally:
        db.close()


def test_fresh_db_has_new_schema(tmp_path):
    """A brand-new DB goes straight to v0.7.0 schema — no migration needed."""
    db = PolilyDB(tmp_path / "fresh.db")
    try:
        cols = {r[1] for r in db.conn.execute("PRAGMA table_info(scan_logs)").fetchall()}
        assert "scheduled_at" in cols
        mon_cols = {r[1] for r in db.conn.execute("PRAGMA table_info(event_monitors)").fetchall()}
        assert "next_check_at" not in mon_cols
    finally:
        db.close()
