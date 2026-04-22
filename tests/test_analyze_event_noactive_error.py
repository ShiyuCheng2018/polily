"""NoActiveAppError surfaces as readable Chinese text in scan_logs."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.scan_log import load_scan_logs
from scanner.tui.service import ScanService


class _FakeNoActiveAppError(Exception):
    """Stand-in whose class name matches Textual's NoActiveAppError exactly."""
    pass


_FakeNoActiveAppError.__name__ = "NoActiveAppError"


@pytest.mark.asyncio
async def test_noactive_app_error_normalized_in_scan_log(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    event = EventRow(
        event_id="evt_noactive",
        slug="noactive-evt",
        title="Test Event",
        tier=None,
        structure_score=None,
    )
    upsert_event(event, db)
    svc = ScanService(config=ScannerConfig(), db=db)

    with patch(
        "scanner.tui.service.NarrativeWriterAgent",
        autospec=False,
    ) as mock_agent_cls:
        mock_agent = mock_agent_cls.return_value
        mock_agent.generate = AsyncMock(side_effect=_FakeNoActiveAppError())
        with pytest.raises(_FakeNoActiveAppError):
            await svc.analyze_event("evt_noactive", trigger_source="manual")

    logs = load_scan_logs(db, limit=1)
    assert logs, "scan_logs should contain the failed run"
    assert logs[0].status == "failed"
    assert logs[0].error == "TUI 已关闭，分析中断"


@pytest.mark.asyncio
async def test_regular_exception_still_formatted_as_before(tmp_path):
    """Regression guard: non-NoActiveAppError exceptions must keep the
    original `"{ClassName}: {msg}"` format so downstream log parsers and
    user troubleshooting don't break."""
    db = PolilyDB(tmp_path / "test.db")
    event = EventRow(
        event_id="evt_regular",
        slug="regular-evt",
        title="Test",
        tier=None,
        structure_score=None,
    )
    upsert_event(event, db)
    svc = ScanService(config=ScannerConfig(), db=db)

    with patch(
        "scanner.tui.service.NarrativeWriterAgent",
        autospec=False,
    ) as mock_agent_cls:
        mock_agent = mock_agent_cls.return_value
        mock_agent.generate = AsyncMock(side_effect=ValueError("boom"))
        with pytest.raises(ValueError):
            await svc.analyze_event("evt_regular", trigger_source="manual")

    logs = load_scan_logs(db, limit=1)
    assert logs[0].status == "failed"
    assert logs[0].error == "ValueError: boom"
