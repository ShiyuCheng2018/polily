"""scan_logs pending/running/superseded/cancelled CRUD."""
from datetime import UTC, datetime, timedelta

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.scan_log import (
    claim_pending_scan,
    fetch_overdue_pending,
    finish_scan,
    insert_pending_scan,
    supersede_pending_for_event,
)


@pytest.fixture
def db(tmp_path):
    d = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), d)
    yield d
    d.close()


def test_insert_pending_creates_row(db):
    sid = insert_pending_scan(
        event_id="ev1",
        event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled",
        scheduled_reason="重要节点",
        db=db,
    )
    row = db.conn.execute("SELECT * FROM scan_logs WHERE scan_id=?", (sid,)).fetchone()
    assert row["status"] == "pending"
    assert row["trigger_source"] == "scheduled"
    assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"
    assert row["scheduled_reason"] == "重要节点"
    assert row["event_id"] == "ev1"
    assert row["market_title"] == "Test"


def test_supersede_pending_marks_previous_rows(db):
    sid1 = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r1", db=db,
    )
    n = supersede_pending_for_event("ev1", db)
    assert n == 1
    row = db.conn.execute("SELECT status FROM scan_logs WHERE scan_id=?", (sid1,)).fetchone()
    assert row["status"] == "superseded"


def test_supersede_pending_ignores_completed_rows(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    db.conn.execute(
        "UPDATE scan_logs SET status='completed' WHERE scan_id=?", (sid,),
    )
    db.conn.commit()
    n = supersede_pending_for_event("ev1", db)
    assert n == 0


def test_claim_pending_moves_to_running(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    ok = claim_pending_scan(sid, db)
    assert ok is True
    row = db.conn.execute("SELECT status, started_at FROM scan_logs WHERE scan_id=?", (sid,)).fetchone()
    assert row["status"] == "running"
    assert row["started_at"] != "" and row["started_at"] is not None


def test_claim_pending_is_idempotent(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    assert claim_pending_scan(sid, db) is True
    assert claim_pending_scan(sid, db) is False


def test_claim_pending_is_thread_safe():
    """Two threads racing to claim the same pending row: exactly one wins."""
    import tempfile
    import threading
    from pathlib import Path

    from scanner.core.db import PolilyDB
    from scanner.core.event_store import EventRow, upsert_event

    with tempfile.TemporaryDirectory() as td:
        db_path = Path(td) / "race.db"
        setup_db = PolilyDB(db_path)
        upsert_event(EventRow(event_id="ev1", title="T", updated_at="now"), setup_db)
        sid = insert_pending_scan(
            event_id="ev1", event_title="T",
            scheduled_at="2026-05-01T10:00:00+00:00",
            trigger_source="scheduled", scheduled_reason="r", db=setup_db,
        )
        setup_db.close()

        wins: list[bool] = []
        barrier = threading.Barrier(parties=2)

        def race():
            d = PolilyDB(db_path)
            try:
                barrier.wait()
                wins.append(claim_pending_scan(sid, d))
            finally:
                d.close()

        t1 = threading.Thread(target=race)
        t2 = threading.Thread(target=race)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert wins.count(True) == 1
        assert wins.count(False) == 1


def test_finish_scan_completed(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    claim_pending_scan(sid, db)
    finish_scan(sid, status="completed", db=db)
    row = db.conn.execute(
        "SELECT status, finished_at, total_elapsed FROM scan_logs WHERE scan_id=?", (sid,),
    ).fetchone()
    assert row["status"] == "completed"
    assert row["finished_at"] is not None


def test_finish_scan_failed_with_error(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    claim_pending_scan(sid, db)
    finish_scan(sid, status="failed", error="Claude CLI timeout", db=db)
    row = db.conn.execute("SELECT status, error FROM scan_logs WHERE scan_id=?", (sid,)).fetchone()
    assert row["status"] == "failed"
    assert row["error"] == "Claude CLI timeout"


def test_fetch_overdue_pending_returns_rows_past_scheduled(db):
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="scheduled", scheduled_reason="due", db=db,
    )
    insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=future,
        trigger_source="scheduled", scheduled_reason="later", db=db,
    )
    overdue = fetch_overdue_pending(db)
    assert len(overdue) == 1
    assert overdue[0]["scheduled_reason"] == "due"


def test_fetch_overdue_pending_excludes_events_with_running_row(db):
    """Q1 decision: dispatcher skips events that already have a running row."""
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    sid_running = insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="manual", scheduled_reason=None, db=db,
    )
    claim_pending_scan(sid_running, db)
    insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="scheduled", scheduled_reason="due", db=db,
    )
    overdue = fetch_overdue_pending(db)
    assert overdue == []
