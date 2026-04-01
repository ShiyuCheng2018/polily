"""Tests for SQLite-backed scan log."""

import tempfile
from pathlib import Path

from scanner.db import PolilyDB
from scanner.scan_log import (
    ScanLogEntry,
    ScanStepRecord,
    create_log_entry,
    finish_log_entry,
    load_scan_logs,
    save_scan_log,
)


def _make_db():
    tmp = tempfile.mkdtemp()
    return PolilyDB(Path(tmp) / "polily.db")


def test_create_running_entry():
    entry = create_log_entry()
    assert entry.status == "running"
    assert entry.started_at is not None
    assert entry.finished_at is None


def test_finish_entry_completed():
    entry = create_log_entry()
    steps = [
        ScanStepRecord(name="fetch", status="done", detail="100 markets", elapsed=3.2),
        ScanStepRecord(name="filter", status="done", detail="20 passed", elapsed=0.5),
    ]
    finish_log_entry(entry, "completed", steps,
                     total_markets=100, research_count=5,
                     watchlist_count=3, filtered_count=12)
    assert entry.status == "completed"
    assert entry.finished_at is not None
    assert entry.research_count == 5


def test_finish_entry_failed():
    entry = create_log_entry()
    finish_log_entry(entry, "failed", [], error="timeout")
    assert entry.status == "failed"
    assert entry.error == "timeout"


def test_save_and_load():
    db = _make_db()
    entry = create_log_entry()
    entry.type = "scan"
    finish_log_entry(entry, "completed",
                     [ScanStepRecord(name="test", status="done", elapsed=1.0)],
                     total_markets=50, research_count=3)
    save_scan_log(entry, db)
    loaded = load_scan_logs(db)
    assert len(loaded) == 1
    assert loaded[0].scan_id == entry.scan_id
    assert loaded[0].type == "scan"
    assert loaded[0].research_count == 3
    db.close()


def test_save_analyze_type():
    db = _make_db()
    entry = create_log_entry()
    entry.type = "analyze"
    entry.market_id = "0xabc"
    entry.market_title = "BTC 68000"
    finish_log_entry(entry, "completed", [])
    save_scan_log(entry, db)
    loaded = load_scan_logs(db)
    assert loaded[0].type == "analyze"
    assert loaded[0].market_id == "0xabc"
    assert loaded[0].market_title == "BTC 68000"
    db.close()


def test_steps_persisted_as_json():
    db = _make_db()
    entry = create_log_entry()
    steps = [
        ScanStepRecord(name="step1", status="done", detail="ok", elapsed=1.0),
        ScanStepRecord(name="step2", status="skip", detail="n/a", elapsed=0.0),
    ]
    finish_log_entry(entry, "completed", steps)
    save_scan_log(entry, db)
    loaded = load_scan_logs(db)
    assert len(loaded[0].steps) == 2
    assert loaded[0].steps[0].name == "step1"
    assert loaded[0].steps[1].status == "skip"
    db.close()


def test_multiple_logs_ordered():
    db = _make_db()
    for i in range(5):
        entry = create_log_entry()
        entry.scan_id = f"scan_{i:03d}"
        finish_log_entry(entry, "completed", [])
        save_scan_log(entry, db)
    loaded = load_scan_logs(db)
    assert len(loaded) == 5
    # Most recent first
    assert loaded[0].scan_id == "scan_004"
    db.close()


def test_no_truncation():
    """SQLite version has no max_entries limit."""
    db = _make_db()
    for i in range(50):
        entry = create_log_entry()
        entry.scan_id = f"scan_{i:03d}"
        save_scan_log(entry, db)
    loaded = load_scan_logs(db)
    assert len(loaded) == 50
    db.close()
