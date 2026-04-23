"""Q3: turning auto_monitor off supersedes all same-event pending rows."""
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event
from polily.core.monitor_store import upsert_event_monitor
from polily.scan_log import insert_pending_scan
from polily.tui.service import PolilyService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    s = PolilyService(config=cfg, db=db)
    yield s
    db.close()


def test_disable_monitor_supersedes_pending(svc):
    insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=svc.db,
    )
    svc.toggle_monitor("ev1", enable=False)
    row = svc.db.conn.execute(
        "SELECT status FROM scan_logs WHERE event_id='ev1'"
    ).fetchone()
    assert row["status"] == "superseded"


def test_enable_monitor_does_not_touch_pending(svc):
    svc.toggle_monitor("ev1", enable=False)
    insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=svc.db,
    )
    svc.toggle_monitor("ev1", enable=True)
    row = svc.db.conn.execute(
        "SELECT status FROM scan_logs WHERE event_id='ev1'"
    ).fetchone()
    assert row["status"] == "pending"


def test_disable_monitor_supersedes_all_pending_rows_not_just_one(svc):
    """Regression: if multiple pending rows exist for the same event (leftover
    from a bug or a manual seed), disable must sweep ALL of them."""
    for t in [
        "2026-05-01T10:00:00+00:00",
        "2026-06-01T10:00:00+00:00",
        "2026-07-01T10:00:00+00:00",
    ]:
        insert_pending_scan(
            event_id="ev1", event_title="Test",
            scheduled_at=t, trigger_source="scheduled",
            scheduled_reason="r", db=svc.db,
        )
    svc.toggle_monitor("ev1", enable=False)
    statuses = [
        r["status"] for r in svc.db.conn.execute(
            "SELECT status FROM scan_logs WHERE event_id='ev1'",
        ).fetchall()
    ]
    assert all(s == "superseded" for s in statuses)
    assert len(statuses) == 3
