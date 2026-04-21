"""EventDetailView — `t` key (and action_trade) blocked on unmonitored events.

Contract:
- Pressing `t` on an unmonitored event does NOT push TradeDialog; it
  surfaces a toast telling the user to activate monitoring first.
- Pressing `t` on a monitored event pushes TradeDialog as usual.

Rationale: trading an event we aren't polling/movement-tracking is a
data-coherence foot-gun — the position would show up in the portfolio
without any price sync or narrator attention until the user later
toggles monitoring on. Forcing monitor-first keeps those paths in sync.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
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


def _seed(svc, *, monitored: bool) -> None:
    upsert_event(EventRow(event_id="ev1", title="Some Event", updated_at="now"), svc.db)
    upsert_market(
        MarketRow(market_id="m1", event_id="ev1", question="Q", updated_at="now"),
        svc.db,
    )
    upsert_event_monitor("ev1", auto_monitor=monitored, db=svc.db)
    svc.db.conn.commit()


class _Host(App):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.pushed_modals: list = []

    def compose(self) -> ComposeResult:
        yield self._view

    def push_screen(self, screen, callback=None):
        self.pushed_modals.append((screen, callback))


@pytest.mark.asyncio
async def test_trade_blocked_when_event_not_monitored(monkeypatch):
    """Pressing `t` on an unmonitored event must notify + NOT push modal."""
    from scanner.tui.views.event_detail import EventDetailView

    svc = _service()
    _seed(svc, monitored=False)
    view = EventDetailView("ev1", svc)
    host = _Host(view)

    async with host.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        notify_calls: list[tuple] = []
        monkeypatch.setattr(view, "notify", lambda msg, **kw: notify_calls.append((msg, kw)))

        view.focus()
        await pilot.press("t")
        await pilot.pause()
        pushed = list(host.pushed_modals)

    # No TradeDialog modal pushed — the guard fired instead.
    assert not pushed, f"TradeDialog should NOT be pushed on unmonitored event, got {pushed}"
    # User got the block toast.
    assert notify_calls, "Expected a notify() call explaining the block"
    msg, kw = notify_calls[0]
    assert "监控" in msg, f"Block message should mention 监控: {msg!r}"
    assert "交易" in msg, f"Block message should mention 交易: {msg!r}"
    # Tonally this is a warning (consistent with monitor-off block pattern).
    assert kw.get("severity") == "warning", \
        f"Expected severity='warning', got {kw.get('severity')!r}"


@pytest.mark.asyncio
async def test_trade_opens_dialog_when_event_is_monitored():
    """Regression: pressing `t` on a monitored event still opens TradeDialog."""
    from scanner.tui.views.event_detail import EventDetailView
    from scanner.tui.views.trade_dialog import TradeDialog

    svc = _service()
    _seed(svc, monitored=True)
    view = EventDetailView("ev1", svc)
    host = _Host(view)

    async with host.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        view.focus()
        await pilot.press("t")
        await pilot.pause()
        pushed = list(host.pushed_modals)

    assert len(pushed) == 1, f"Expected TradeDialog push, got {pushed}"
    modal, _cb = pushed[0]
    assert isinstance(modal, TradeDialog)
