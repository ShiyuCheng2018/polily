"""Q9: cancel a running scan via PolilyService + TUI key binding."""
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event
from polily.scan_log import claim_pending_scan, insert_pending_scan
from polily.tui.service import PolilyService


@pytest.fixture(autouse=True)
def _clear_registry():
    """Reset narrator_registry between tests — module-level state."""
    from polily.agents import narrator_registry
    narrator_registry._active.clear()
    yield
    narrator_registry._active.clear()


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
    s = PolilyService(config=cfg, db=db)
    yield s
    db.close()


def test_cancel_running_scan_kills_narrator_and_marks_row(svc):
    from polily.agents import narrator_registry
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


def test_cancel_marks_row_when_narrator_not_in_registry(svc):
    """Cross-process scenario: the narrator is running in the daemon
    process and isn't in the TUI's narrator_registry. The TUI's cancel
    still flips the DB row to 'cancelled' so the user's intent is
    recorded, and the next finish_scan from the daemon is a no-op
    (see test_finish_scan_does_not_overwrite_terminal_state in
    test_scan_log_lifecycle.py).

    This test does NOT claim cross-process narrator subprocess
    termination — see narrator_registry.py docstring for the scope
    limitation. Quota burn until the daemon narrator finishes is
    documented behavior for this release.
    """
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=svc.db,
    )
    claim_pending_scan(sid, svc.db)
    # Intentionally DO NOT register a narrator — represents the
    # daemon-initiated case where the TUI's registry is empty.

    result = svc.cancel_running_scan(sid)

    assert result is True, "DB row flip must succeed even without registry hit"
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
