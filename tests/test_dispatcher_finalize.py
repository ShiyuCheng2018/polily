"""Verify that ANY exception in _run_pending_analysis (including
exceptions raised before service.analyze_event is reached) results
in the scan_logs row being marked status='failed', not left in
'running' indefinitely.

Pre-v0.11.4: dispatcher's outer try/except only wrapped asyncio.run(...)
and `service = PolilyService(...)` was OUTSIDE the try. If
PolilyService.__init__ raised (or analyze_event itself raised an
exception not caught internally), the row stayed 'running' forever
and only fail_orphan_running on next daemon restart could clean it up.

Real prod incident 2026-05-04 21:38: 2 rows stuck running 12+ minutes
because of sqlite3.InterfaceError that escaped the try block.
"""
from __future__ import annotations

import pytest

from polily.scan_log import claim_pending_scan, insert_pending_scan


@pytest.mark.asyncio
async def test_dispatcher_marks_row_failed_when_service_init_raises(
    polily_db, monkeypatch,
):
    """Service init raises → row goes from running → failed (with error msg)."""
    from datetime import UTC, datetime

    from polily.daemon import poll_job

    # Seed an event_monitor + pending scan_logs row
    polily_db.conn.execute(
        "INSERT INTO events(event_id, title, slug, market_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("test_event_1", "Test event", "test", 1, datetime.now(UTC).isoformat()),
    )
    insert_pending_scan(
        event_id="test_event_1",
        event_title="Test event",
        scheduled_at=datetime.now(UTC).isoformat(),
        trigger_source="movement",
        scheduled_reason="test",
        db=polily_db,
    )

    # Find the inserted scan_id, claim it (mimics dispatcher claim step)
    row = polily_db.conn.execute(
        "SELECT scan_id FROM scan_logs WHERE event_id=? AND status='pending'",
        ("test_event_1",),
    ).fetchone()
    scan_id = row["scan_id"]
    assert claim_pending_scan(scan_id, polily_db), "claim should succeed"

    # Force PolilyService.__init__ to raise
    def _broken_init(self, *args, **kwargs):
        raise RuntimeError("Simulated init failure (ICU rehearsal for BUG-4 class)")

    from polily.tui.service import PolilyService
    monkeypatch.setattr(PolilyService, "__init__", _broken_init)

    # Set up minimal _ctx so dispatcher doesn't crash on `_ctx.config`
    class _FakeCtx:
        config = None
        scheduler = None
    monkeypatch.setattr(poll_job, "_ctx", _FakeCtx())

    # Call the function the dispatcher would call
    poll_job._run_pending_analysis(
        event_id="test_event_1",
        scan_id=scan_id,
        db=polily_db,
        trigger_source="movement",
    )

    # Assert: row is now 'failed', not 'running'
    final_row = polily_db.conn.execute(
        "SELECT status, error FROM scan_logs WHERE scan_id=?", (scan_id,),
    ).fetchone()
    assert final_row["status"] == "failed", (
        f"Expected status='failed', got '{final_row['status']}'. "
        f"Pre-v0.11.4 this stayed 'running' because dispatcher's try/except "
        f"didn't wrap PolilyService.__init__."
    )
    assert final_row["error"], "error message should be populated"
    assert "RuntimeError" in final_row["error"] or "Simulated init failure" in final_row["error"], (
        f"error should mention the original exception type/msg. Got: {final_row['error']}"
    )


@pytest.mark.asyncio
async def test_dispatcher_handles_finish_scan_double_failure(
    polily_db, monkeypatch,
):
    """Belt-and-suspenders: even if BOTH analyze_event AND finish_scan raise,
    the function returns cleanly (no double-exception crash). Row stays
    running but daemon doesn't crash."""
    from datetime import UTC, datetime

    from polily.daemon import poll_job

    polily_db.conn.execute(
        "INSERT INTO events(event_id, title, slug, market_count, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("test_event_2", "Test", "t", 1, datetime.now(UTC).isoformat()),
    )
    insert_pending_scan(
        event_id="test_event_2",
        event_title="Test",
        scheduled_at=datetime.now(UTC).isoformat(),
        trigger_source="movement",
        scheduled_reason="test",
        db=polily_db,
    )
    row = polily_db.conn.execute(
        "SELECT scan_id FROM scan_logs WHERE event_id=? AND status='pending'",
        ("test_event_2",),
    ).fetchone()
    scan_id = row["scan_id"]
    assert claim_pending_scan(scan_id, polily_db)

    # Both inits fail
    from polily.tui.service import PolilyService
    monkeypatch.setattr(
        PolilyService, "__init__",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("init failed")),
    )

    # finish_scan also fails
    import polily.scan_log as sl
    monkeypatch.setattr(
        sl, "finish_scan",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("finish_scan also failed")),
    )

    class _FakeCtx:
        config = None
        scheduler = None
    monkeypatch.setattr(poll_job, "_ctx", _FakeCtx())

    # Should not raise — both exceptions are swallowed with logging
    poll_job._run_pending_analysis(
        event_id="test_event_2",
        scan_id=scan_id,
        db=polily_db,
        trigger_source="movement",
    )
    # No assertion on final state — row may be 'running' (because finish_scan
    # itself failed). What we assert is THIS FUNCTION DID NOT RAISE.
