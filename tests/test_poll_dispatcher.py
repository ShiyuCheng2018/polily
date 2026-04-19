"""Poll tick dispatcher: overdue pending → running via ai executor."""
from datetime import UTC, datetime, timedelta

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.monitor_store import upsert_event_monitor
from scanner.scan_log import insert_pending_scan


@pytest.fixture
def db(tmp_path):
    d = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), d)
    upsert_event_monitor("ev1", auto_monitor=True, db=d)
    yield d
    d.close()


def test_dispatch_overdue_pending_submits_to_ai_executor(db):
    from scanner.daemon.poll_job import dispatch_pending_analyses

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="scheduled", scheduled_reason="due", db=db,
    )
    submitted = []

    class FakeScheduler:
        def add_job(self, func, **kwargs):
            submitted.append((func.__name__, kwargs.get("kwargs", {}).get("scan_id")))

    dispatch_pending_analyses(db=db, scheduler=FakeScheduler())
    assert len(submitted) == 1
    assert submitted[0][1] == sid
    row = db.conn.execute("SELECT status FROM scan_logs WHERE scan_id=?", (sid,)).fetchone()
    assert row["status"] == "running"


def test_dispatch_skips_future_pending(db):
    from scanner.daemon.poll_job import dispatch_pending_analyses

    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=future,
        trigger_source="scheduled", scheduled_reason="later", db=db,
    )
    submitted = []

    class FakeScheduler:
        def add_job(self, func, **kwargs):
            submitted.append(kwargs)

    dispatch_pending_analyses(db=db, scheduler=FakeScheduler())
    assert submitted == []


def test_dispatch_skips_event_with_running_row(db):
    """Q1: NOT EXISTS running guard in dispatcher query."""
    from scanner.daemon.poll_job import dispatch_pending_analyses
    from scanner.scan_log import claim_pending_scan

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    sid_running = insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="manual", scheduled_reason=None, db=db,
    )
    claim_pending_scan(sid_running, db)  # now running
    insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="scheduled", scheduled_reason="due", db=db,
    )
    submitted = []

    class FakeScheduler:
        def add_job(self, func, **kwargs):
            submitted.append(kwargs)

    dispatch_pending_analyses(db=db, scheduler=FakeScheduler())
    assert submitted == []


def test_dispatch_continues_past_add_job_failure(db):
    """Important fix: one add_job failure must not abort the batch.

    Seed two overdue rows for different events. Make add_job raise on the
    first call but succeed on the second. Expect submitted == 1 (second
    made it through) and the first row stays in 'running' — it's left for
    fail_orphan_running to sweep on daemon restart.
    """
    from scanner.daemon.poll_job import dispatch_pending_analyses

    # Seed a second event so fetch_overdue_pending returns two rows
    # (it caps at earliest-per-event, so we need distinct events).
    upsert_event(EventRow(event_id="ev2", title="Test2", updated_at="now"), db)
    upsert_event_monitor("ev2", auto_monitor=True, db=db)

    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    sid1 = insert_pending_scan(
        event_id="ev1", event_title="Test", scheduled_at=past,
        trigger_source="scheduled", scheduled_reason="due", db=db,
    )
    sid2 = insert_pending_scan(
        event_id="ev2", event_title="Test2", scheduled_at=past,
        trigger_source="scheduled", scheduled_reason="due", db=db,
    )

    submitted_ids: list[str] = []

    class FlakyScheduler:
        def __init__(self):
            self.calls = 0

        def add_job(self, func, **kwargs):
            self.calls += 1
            scan_id = kwargs.get("kwargs", {}).get("scan_id")
            if self.calls == 1:
                raise RuntimeError("simulated scheduler failure")
            submitted_ids.append(scan_id)

    n = dispatch_pending_analyses(db=db, scheduler=FlakyScheduler())
    assert n == 1  # second row got through
    assert len(submitted_ids) == 1

    # Identify which one failed and which succeeded. fetch_overdue_pending
    # orders by scheduled_at ASC; with equal scheduled_at order is not
    # guaranteed, so just assert the two scan_ids split between the two
    # outcomes as expected.
    ok_id = submitted_ids[0]
    failed_id = sid2 if ok_id == sid1 else sid1

    # The failed row is still 'running' (not reverted to 'pending').
    row_failed = db.conn.execute(
        "SELECT status FROM scan_logs WHERE scan_id=?", (failed_id,),
    ).fetchone()
    assert row_failed["status"] == "running"

    # The succeeded row is also 'running' (claim_pending_scan flipped it).
    row_ok = db.conn.execute(
        "SELECT status FROM scan_logs WHERE scan_id=?", (ok_id,),
    ).fetchone()
    assert row_ok["status"] == "running"


def test_dispatch_dispatches_earliest_pending_per_event_only(db):
    """B4 regression: multiple stale pending rows for the same event
    (e.g. after long laptop sleep) must NOT dispatch multiple agents."""
    from scanner.daemon.poll_job import dispatch_pending_analyses

    now = datetime.now(UTC)
    insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at=(now - timedelta(hours=3)).isoformat(),
        trigger_source="scheduled", scheduled_reason="oldest", db=db,
    )
    insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at=(now - timedelta(hours=2)).isoformat(),
        trigger_source="scheduled", scheduled_reason="middle", db=db,
    )
    insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at=(now - timedelta(hours=1)).isoformat(),
        trigger_source="scheduled", scheduled_reason="newest", db=db,
    )
    submitted = []

    class FakeScheduler:
        def add_job(self, func, **kwargs):
            submitted.append(kwargs.get("kwargs", {}).get("scan_id"))

    dispatch_pending_analyses(db=db, scheduler=FakeScheduler())
    assert len(submitted) == 1
    running = db.conn.execute(
        "SELECT scheduled_reason FROM scan_logs WHERE status='running'",
    ).fetchone()
    assert running["scheduled_reason"] == "oldest"


def test_movement_trigger_writes_pending_row(db):
    """Q5: movement path writes scan_logs pending instead of direct add_job."""
    from scanner.daemon.poll_job import _trigger_movement_analysis

    _trigger_movement_analysis(
        event_id="ev1", event_title="Test", reason="M=85 Q=72", db=db,
    )
    row = db.conn.execute(
        "SELECT status, trigger_source, scheduled_reason FROM scan_logs "
        "WHERE event_id='ev1' AND status='pending'",
    ).fetchone()
    assert row is not None
    assert row["trigger_source"] == "movement"
    assert "M=85" in row["scheduled_reason"]
