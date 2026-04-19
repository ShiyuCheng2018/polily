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
