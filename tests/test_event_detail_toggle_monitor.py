"""EventDetailView — `m` key behavior for the monitor lifecycle.

Contract:
- Enabling monitor is silent (no modal, no block).
- Disabling is blocked entirely when any market of the event has positions
  (notifies the user, does not push a modal, leaves auto_monitor=1).
- Disabling with no positions pushes ConfirmUnmonitorModal; the actual
  toggle only runs on True-dismiss.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import get_event_monitor, upsert_event_monitor
from scanner.tui.service import ScanService


def _service():
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    cfg.wallet.starting_balance = 100.0
    tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(tmp.name) / "t.db")
    svc = ScanService(config=cfg, db=db)
    svc._tmp = tmp
    return svc


def _seed(svc, with_position: bool, monitored: bool = True) -> None:
    upsert_event(EventRow(event_id="ev1", title="Some Event", updated_at="now"), svc.db)
    upsert_market(
        MarketRow(market_id="m1", event_id="ev1", question="Q", updated_at="now"),
        svc.db,
    )
    upsert_event_monitor("ev1", auto_monitor=monitored, db=svc.db)
    if with_position:
        svc.db.conn.execute(
            "INSERT INTO positions (event_id, market_id, side, shares, avg_cost, "
            "cost_basis, title, opened_at, updated_at) "
            "VALUES ('ev1', 'm1', 'yes', 10.0, 0.5, 5.0, 'Q', 'now', 'now')",
        )
    svc.db.conn.commit()


class _Host(App):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.pushed_modals: list = []
        self.notified: list[tuple[str, str | None]] = []

    def compose(self) -> ComposeResult:
        yield self._view

    def push_screen(self, screen, callback=None):
        self.pushed_modals.append((screen, callback))


@pytest.mark.asyncio
async def test_pressing_m_on_unmonitored_enables_silently():
    from scanner.tui.views.event_detail import EventDetailView

    svc = _service()
    _seed(svc, with_position=False, monitored=False)
    view = EventDetailView("ev1", svc)
    host = _Host(view)

    async with host.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        view.focus()
        await pilot.press("m")
        await pilot.pause()
        pushed = list(host.pushed_modals)

    # Enabled directly, no modal pushed
    assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 1
    assert not pushed


@pytest.mark.asyncio
async def test_pressing_m_with_positions_is_blocked(monkeypatch):
    from scanner.tui.views.event_detail import EventDetailView

    svc = _service()
    _seed(svc, with_position=True, monitored=True)
    view = EventDetailView("ev1", svc)
    host = _Host(view)

    async with host.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        notify_calls: list[tuple] = []
        monkeypatch.setattr(view, "notify", lambda msg, **kw: notify_calls.append((msg, kw)))

        view.focus()
        await pilot.press("m")
        await pilot.pause()
        pushed = list(host.pushed_modals)

    # auto_monitor stays 1 — the block worked
    assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 1
    # No modal pushed — we notify inline, don't ask
    assert not pushed
    # User got a clear block message
    assert notify_calls
    msg, _kw = notify_calls[0]
    assert "无法" in msg and "持仓" in msg


@pytest.mark.asyncio
async def test_pressing_m_without_positions_pushes_modal():
    from scanner.tui.views.event_detail import EventDetailView
    from scanner.tui.views.monitor_modals import ConfirmUnmonitorModal

    svc = _service()
    _seed(svc, with_position=False, monitored=True)
    view = EventDetailView("ev1", svc)
    host = _Host(view)

    async with host.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        view.focus()
        await pilot.press("m")
        await pilot.pause()
        pushed = list(host.pushed_modals)

    # Modal pushed, NOT yet toggled (will only toggle on confirm)
    assert len(pushed) == 1
    modal, _cb = pushed[0]
    assert isinstance(modal, ConfirmUnmonitorModal)
    assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 1


@pytest.mark.asyncio
async def test_modal_confirm_flips_monitor_off():
    """The dismiss callback — called with True — is what actually toggles."""
    from scanner.tui.views.event_detail import EventDetailView

    svc = _service()
    _seed(svc, with_position=False, monitored=True)
    view = EventDetailView("ev1", svc)

    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        view.focus()
        await pilot.press("m")
        await pilot.pause()

        _modal, callback = view.app.pushed_modals[0]
        callback(True)  # simulate confirm
        await pilot.pause()

    assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 0


@pytest.mark.asyncio
async def test_modal_cancel_keeps_monitor_on():
    from scanner.tui.views.event_detail import EventDetailView

    svc = _service()
    _seed(svc, with_position=False, monitored=True)
    view = EventDetailView("ev1", svc)

    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        view.focus()
        await pilot.press("m")
        await pilot.pause()

        _modal, callback = view.app.pushed_modals[0]
        callback(False)  # simulate keep monitoring
        await pilot.pause()

    assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 1
