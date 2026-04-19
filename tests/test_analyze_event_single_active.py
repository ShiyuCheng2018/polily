"""I1 regression: analyze_event must reject if another running row exists
for the same event (prevents double-narrator race on fast repeated press of `a`).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.scan_log import claim_pending_scan, insert_pending_scan
from scanner.tui.service import AnalysisInProgressError, ScanService


def _mk_service(tmp_path):
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    cfg.wallet.starting_balance = 100.0
    cfg.ai.narrative_writer = MagicMock(model="sonnet", timeout_seconds=60)
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
    return ScanService(config=cfg, db=db), db


@pytest.mark.asyncio
async def test_analyze_event_rejects_when_running_row_exists(tmp_path):
    """If another running row exists for the event, a manual analyze_event
    MUST raise AnalysisInProgressError before touching the narrator."""
    svc, db = _mk_service(tmp_path)
    # Seed a running row
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    claim_pending_scan(sid, db)  # now running

    narrator_gen = AsyncMock()
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = narrator_gen
        Mock.return_value.cancel = MagicMock()
        with pytest.raises(AnalysisInProgressError):
            await svc.analyze_event("ev1", trigger_source="manual")

    # Narrator must NOT have been called
    narrator_gen.assert_not_called()
    # DB must NOT have a second running row
    rows = db.conn.execute(
        "SELECT COUNT(*) FROM scan_logs WHERE event_id='ev1' AND status='running'",
    ).fetchone()[0]
    assert rows == 1, "only the pre-existing running row should remain"


@pytest.mark.asyncio
async def test_analyze_event_proceeds_when_no_running_exists(tmp_path):
    """Baseline: no running row → analyze_event proceeds normally."""
    from scanner.agents.schemas import NarrativeWriterOutput

    svc, db = _mk_service(tmp_path)
    narr = NarrativeWriterOutput(
        event_id="ev1", mode="discovery", summary="s",
        next_check_at="2099-05-01T10:00:00+00:00",
        next_check_reason="later",
    )
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = AsyncMock(return_value=narr)
        Mock.return_value.cancel = MagicMock()
        await svc.analyze_event("ev1", trigger_source="manual")

    completed = db.conn.execute(
        "SELECT COUNT(*) FROM scan_logs WHERE event_id='ev1' AND status='completed'",
    ).fetchone()[0]
    assert completed == 1


@pytest.mark.asyncio
async def test_dispatcher_supplied_scan_id_bypasses_guard(tmp_path):
    """When the dispatcher passes scan_id (already claimed), the guard must NOT
    fire — the dispatcher has already atomically claimed the row via
    claim_pending_scan, which respects fetch_overdue_pending's NOT EXISTS
    running. Running counts don't match because the claimed row IS the
    running one the caller is about to execute."""
    from scanner.agents.schemas import NarrativeWriterOutput

    svc, db = _mk_service(tmp_path)
    sid = insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="r", db=db,
    )
    claim_pending_scan(sid, db)  # now running — represents dispatcher claim

    narr = NarrativeWriterOutput(
        event_id="ev1", mode="discovery", summary="s",
    )
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = AsyncMock(return_value=narr)
        Mock.return_value.cancel = MagicMock()
        # Pass scan_id=sid → tells analyze_event "this is the dispatched row"
        await svc.analyze_event(
            "ev1", trigger_source="scheduled", scan_id=sid,
        )

    row = db.conn.execute(
        "SELECT status FROM scan_logs WHERE scan_id=?", (sid,),
    ).fetchone()
    assert row["status"] == "completed"
