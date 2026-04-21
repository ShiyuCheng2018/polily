"""Integration-level check: pressing `r` on every content view does not
crash the app. Catches the exact bug the user hit in interactive use."""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.events import EventBus
from scanner.core.monitor_store import upsert_event_monitor
from scanner.scan_log import ScanLogEntry, insert_pending_scan
from scanner.tui.service import ScanService


def _service_with_event():
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(tmp.name) / "t.db")
    upsert_event(
        EventRow(
            event_id="ev1", title="Test Event", slug="test-slug",
            updated_at="now",
        ),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1", event_id="ev1", question="Q",
            yes_price=0.42, updated_at="now",
        ),
        db,
    )
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    svc = ScanService(config=cfg, db=db, event_bus=EventBus())
    svc._tmp = tmp
    return svc


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_event_detail():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView("ev1", svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_score_result():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.score_result import ScoreResultView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScoreResultView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_scan_log_list():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogView

    svc = _service_with_event()
    insert_pending_scan(
        event_id="ev1", event_title="Test Event",
        scheduled_at=datetime.now(UTC).isoformat(),
        trigger_source="manual", scheduled_reason=None, db=svc.db,
    )
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_scan_log_detail():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogDetailView

    svc = _service_with_event()
    insert_pending_scan(
        event_id="ev1", event_title="Test Event",
        scheduled_at=datetime.now(UTC).isoformat(),
        trigger_source="manual", scheduled_reason="test",
        db=svc.db,
    )
    from scanner.scan_log import load_scan_logs
    entry = load_scan_logs(svc.db)[0]

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogDetailView(entry, db=svc.db)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_wallet():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.wallet import WalletView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = WalletView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_monitor_list():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_paper_status():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.paper_status import PaperStatusView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_history():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.history import HistoryView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = HistoryView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_repeated_does_not_duplicate_tables_monitor():
    """Regression: rapid `r` presses must not DuplicateIds on the table.

    v0.8.0 bug: `_render_all` did `child.remove()` + `zone.mount()` — but
    Textual's `remove()` is deferred, so manual sync refresh raced the
    new mount and tripped DuplicateIds('monitor-table')."""
    from textual.widgets import DataTable
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        for _ in range(5):
            await pilot.press("r")
            await pilot.pause()
        tables = list(view.query("#monitor-table"))
        assert len(tables) == 1, f"expected exactly 1 monitor-table, found {len(tables)}"
        assert isinstance(tables[0], DataTable)


@pytest.mark.asyncio
async def test_r_refresh_repeated_does_not_duplicate_tables_scan_log():
    """Same regression for ScanLogView — both pending and history tables."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogView

    svc = _service_with_event()
    insert_pending_scan(
        event_id="ev1", event_title="Test Event",
        scheduled_at=datetime.now(UTC).isoformat(),
        trigger_source="manual", scheduled_reason=None, db=svc.db,
    )
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        for _ in range(5):
            await pilot.press("r")
            await pilot.pause()
        up = list(view.query("#upcoming-table"))
        hist = list(view.query("#history-table"))
        assert len(up) == 1, f"expected 1 upcoming-table, found {len(up)}"
        assert len(hist) == 1, f"expected 1 history-table, found {len(hist)}"


@pytest.mark.asyncio
async def test_r_refresh_in_real_main_screen_flow():
    """Realistic flow: start the full app, navigate via sidebar, press `r`
    multiple times. Closer to the interactive crash the user hit."""
    from scanner.tui.app import PolilyApp

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        # Navigate via digit keys (sidebar shortcuts)
        for menu_key in ("0", "1", "2", "3", "4", "5"):
            await pilot.press(menu_key)
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            # Press r again — catches "recompose after recompose" issues
            await pilot.press("r")
            await pilot.pause()


@pytest.mark.asyncio
async def test_r_refresh_does_not_crash_archived():
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.archived_events import ArchivedEventsView

    svc = _service_with_event()
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ArchivedEventsView(svc)
        await app.mount(view)
        await pilot.pause()
        view.focus()
        await pilot.press("r")
        await pilot.pause()
