"""ScanService.analyze_event must write scan_logs running→completed + next pending."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.agents.schemas import NarrativeWriterOutput
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import ScanService


def _mk_service(tmp_path):
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    cfg.wallet.starting_balance = 100.0
    cfg.ai.narrative_writer = MagicMock(model="sonnet", timeout_seconds=60)
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
    upsert_market(MarketRow(market_id="m1", event_id="ev1", question="Q", updated_at="now"), db)
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    return ScanService(config=cfg, db=db), db


@pytest.mark.asyncio
async def test_analyze_writes_running_row_then_completed(tmp_path):
    svc, db = _mk_service(tmp_path)
    narr = NarrativeWriterOutput(
        event_id="ev1", mode="discovery", summary="s",
        next_check_at="2099-05-01T10:00:00+00:00",
        next_check_reason="重要节点",
    )
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = AsyncMock(return_value=narr)
        Mock.return_value.cancel = MagicMock()
        await svc.analyze_event("ev1", trigger_source="manual")

    rows = db.conn.execute(
        "SELECT status, trigger_source FROM scan_logs WHERE event_id='ev1' "
        "ORDER BY started_at"
    ).fetchall()
    statuses = [(r["status"], r["trigger_source"]) for r in rows]
    assert ("completed", "manual") in statuses
    assert ("pending", "scheduled") in statuses


@pytest.mark.asyncio
async def test_analyze_supersedes_prior_pending(tmp_path):
    svc, db = _mk_service(tmp_path)
    from scanner.scan_log import insert_pending_scan
    insert_pending_scan(
        event_id="ev1", event_title="Test",
        scheduled_at="2099-04-30T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="older", db=db,
    )
    narr = NarrativeWriterOutput(
        event_id="ev1", mode="discovery", summary="s",
        next_check_at="2099-05-01T10:00:00+00:00",
        next_check_reason="重要节点",
    )
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = AsyncMock(return_value=narr)
        Mock.return_value.cancel = MagicMock()
        await svc.analyze_event("ev1", trigger_source="manual")

    pending_rows = db.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE event_id='ev1' AND status='pending'"
    ).fetchall()
    assert len(pending_rows) == 1
    assert pending_rows[0]["scheduled_at"] == "2099-05-01T10:00:00+00:00"

    superseded = db.conn.execute(
        "SELECT COUNT(*) FROM scan_logs WHERE event_id='ev1' AND status='superseded'"
    ).fetchone()[0]
    assert superseded == 1


@pytest.mark.asyncio
async def test_analyze_agent_failure_marks_row_failed(tmp_path):
    svc, db = _mk_service(tmp_path)
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = AsyncMock(side_effect=RuntimeError("Claude crashed"))
        Mock.return_value.cancel = MagicMock()
        with pytest.raises(RuntimeError):
            await svc.analyze_event("ev1", trigger_source="manual")

    row = db.conn.execute(
        "SELECT status, error FROM scan_logs WHERE event_id='ev1' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row["status"] == "failed"
    err = row["error"] or ""
    assert "RuntimeError" in err
    assert "Claude crashed" in err


def test_validate_next_check_at_rejects_bad_inputs():
    from scanner.tui.service import _validate_next_check_at

    assert _validate_next_check_at(None) is None
    assert _validate_next_check_at("") is None
    assert _validate_next_check_at("not-a-date") is None
    assert _validate_next_check_at("2020-01-01T00:00:00+00:00") is None
    assert _validate_next_check_at("2099-01-01T00:00:00+00:00") == "2099-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_analyze_skips_pending_insert_when_next_check_invalid(tmp_path):
    svc, db = _mk_service(tmp_path)
    narr = NarrativeWriterOutput(
        event_id="ev1", mode="discovery", summary="s",
        next_check_at="",
        next_check_reason="",
    )
    with patch("scanner.tui.service.NarrativeWriterAgent") as Mock:
        Mock.return_value.generate = AsyncMock(return_value=narr)
        Mock.return_value.cancel = MagicMock()
        await svc.analyze_event("ev1", trigger_source="manual")

    pending = db.conn.execute(
        "SELECT COUNT(*) FROM scan_logs WHERE event_id='ev1' AND status='pending'"
    ).fetchone()[0]
    assert pending == 0
