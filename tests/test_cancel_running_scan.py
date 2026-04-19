"""Q9: cancel a running scan via ScanService + TUI key binding."""
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.scan_log import claim_pending_scan, insert_pending_scan
from scanner.tui.service import ScanService


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset narrator_registry between tests — module-level state."""
    from scanner.agents import narrator_registry
    narrator_registry._active.clear()
    yield
    narrator_registry._active.clear()


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
    s = ScanService(config=cfg, db=db)
    yield s
    db.close()


def test_cancel_running_scan_kills_narrator_and_marks_row(svc):
    from scanner.agents import narrator_registry
    narrator = MagicMock()
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="manual", scheduled_reason=None, db=svc.db,
    )
    claim_pending_scan(sid, svc.db)
    narrator_registry.register(sid, narrator)

    result = svc.cancel_running_scan(sid)

    assert result is True
    narrator.cancel.assert_called_once()
    row = svc.db.conn.execute(
        "SELECT status FROM scan_logs WHERE scan_id=?", (sid,),
    ).fetchone()
    assert row["status"] == "cancelled"


def test_cancel_running_scan_works_for_dispatcher_rows(svc):
    """B2 regression: rows initiated by the daemon dispatcher (different
    ScanService instance) can still be cancelled via the shared registry."""
    from scanner.agents import narrator_registry
    dispatcher_narrator = MagicMock()
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=svc.db,
    )
    claim_pending_scan(sid, svc.db)
    narrator_registry.register(sid, dispatcher_narrator)

    result = svc.cancel_running_scan(sid)

    assert result is True
    dispatcher_narrator.cancel.assert_called_once()
    row = svc.db.conn.execute(
        "SELECT status FROM scan_logs WHERE scan_id=?", (sid,),
    ).fetchone()
    assert row["status"] == "cancelled"


def test_cancel_running_scan_is_noop_on_non_running(svc):
    """Cancelling a pending row is safe and does nothing."""
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="manual", scheduled_reason=None, db=svc.db,
    )
    result = svc.cancel_running_scan(sid)
    assert result is False
    row = svc.db.conn.execute(
        "SELECT status FROM scan_logs WHERE scan_id=?", (sid,),
    ).fetchone()
    assert row["status"] == "pending"
