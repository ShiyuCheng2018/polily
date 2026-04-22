"""Q2: daemon startup marks orphan running rows as failed."""
from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event
from polily.scan_log import claim_pending_scan, fail_orphan_running, insert_pending_scan


def test_fail_orphan_running_marks_all_running_rows_failed(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    try:
        upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
        sid = insert_pending_scan(
            event_id="ev1", event_title="Test",
            scheduled_at="2026-05-01T10:00:00+00:00",
            trigger_source="scheduled", scheduled_reason="r", db=db,
        )
        claim_pending_scan(sid, db)  # now running

        n = fail_orphan_running(db)
        assert n == 1
        row = db.conn.execute(
            "SELECT status, error FROM scan_logs WHERE scan_id=?", (sid,),
        ).fetchone()
        assert row["status"] == "failed"
        assert row["error"] == "进程中断，未完成"
    finally:
        db.close()


def test_fail_orphan_running_ignores_completed_rows(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    try:
        upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
        sid = insert_pending_scan(
            event_id="ev1", event_title="Test",
            scheduled_at="2026-05-01T10:00:00+00:00",
            trigger_source="scheduled", scheduled_reason="r", db=db,
        )
        db.conn.execute(
            "UPDATE scan_logs SET status='completed' WHERE scan_id=?", (sid,),
        )
        db.conn.commit()
        n = fail_orphan_running(db)
        assert n == 0
    finally:
        db.close()
