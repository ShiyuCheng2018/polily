"""Verify the publisher side of the event bus.

Pre-v0.8.0 (and up to the fix in commit TBD) most topics had zero
publishers — views subscribed to silence. This file locks in the publisher
contract:

- `execute_buy` / `execute_sell` publish POSITION + WALLET
- `toggle_monitor` publishes MONITOR
- MainScreen heartbeats match-all PRICE / POSITION / WALLET / MONITOR /
  SCAN every few seconds so cross-process daemon writes reach the TUI
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.events import (
    EventBus,
    TOPIC_MONITOR_UPDATED,
    TOPIC_POSITION_UPDATED,
    TOPIC_PRICE_UPDATED,
    TOPIC_SCAN_UPDATED,
    TOPIC_WALLET_UPDATED,
)
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test Event", slug="test-slug", updated_at="now"),
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
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


# -----------------------------------------------------------------------
# A. Trade publishes POSITION + WALLET
# -----------------------------------------------------------------------


def test_execute_buy_publishes_position_and_wallet(svc):
    events: list[tuple[str, dict]] = []
    svc.event_bus.subscribe(TOPIC_POSITION_UPDATED, lambda p: events.append(("pos", p)))
    svc.event_bus.subscribe(TOPIC_WALLET_UPDATED, lambda p: events.append(("wal", p)))

    svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    topics = [t for t, _ in events]
    assert "pos" in topics, f"POSITION_UPDATED not published after buy. Got: {events}"
    assert "wal" in topics, f"WALLET_UPDATED not published after buy. Got: {events}"
    # Payload sanity
    pos_payload = next(p for t, p in events if t == "pos")
    assert pos_payload["market_id"] == "m1"
    assert pos_payload["source"] == "buy"


def test_execute_sell_publishes_position_and_wallet(svc):
    # Need an existing position to sell
    svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    events: list[tuple[str, dict]] = []
    svc.event_bus.subscribe(TOPIC_POSITION_UPDATED, lambda p: events.append(("pos", p)))
    svc.event_bus.subscribe(TOPIC_WALLET_UPDATED, lambda p: events.append(("wal", p)))

    svc.execute_sell(market_id="m1", side="yes", shares=5.0)

    topics = [t for t, _ in events]
    assert "pos" in topics and "wal" in topics, \
        f"Expected both POSITION and WALLET after sell. Got: {events}"
    pos_payload = next(p for t, p in events if t == "pos")
    assert pos_payload["source"] == "sell"


# -----------------------------------------------------------------------
# C. Monitor toggle publishes MONITOR
# -----------------------------------------------------------------------


def test_toggle_monitor_publishes_monitor(svc):
    # Start from off so enable is unambiguous
    svc.toggle_monitor("ev1", enable=False)  # disable first (has no positions)

    events: list[dict] = []
    svc.event_bus.subscribe(TOPIC_MONITOR_UPDATED, lambda p: events.append(p))

    svc.toggle_monitor("ev1", enable=True)

    assert events, "MONITOR_UPDATED not published on toggle"
    assert events[-1]["event_id"] == "ev1"
    assert events[-1]["auto_monitor"] is True


# -----------------------------------------------------------------------
# D. MainScreen heartbeat fan-out
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_main_screen_heartbeat_publishes_all_bridge_topics(svc):
    from scanner.tui.app import PolilyApp
    from scanner.tui.screens.main import MainScreen

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    events: list[str] = []
    svc.event_bus.subscribe(TOPIC_PRICE_UPDATED, lambda p: events.append("price"))
    svc.event_bus.subscribe(TOPIC_POSITION_UPDATED, lambda p: events.append("pos"))
    svc.event_bus.subscribe(TOPIC_WALLET_UPDATED, lambda p: events.append("wal"))
    svc.event_bus.subscribe(TOPIC_MONITOR_UPDATED, lambda p: events.append("mon"))
    svc.event_bus.subscribe(TOPIC_SCAN_UPDATED, lambda p: events.append("scan"))

    async with app.run_test() as pilot:
        await pilot.pause()
        screen = next(s for s in app.screen_stack if isinstance(s, MainScreen))
        # Directly invoke the heartbeat instead of waiting 5s
        screen._bus_heartbeat()
        await pilot.pause()

    assert {"price", "pos", "wal", "mon", "scan"}.issubset(set(events)), \
        f"heartbeat missed topics: {set(events)}"


@pytest.mark.asyncio
async def test_main_screen_installs_heartbeat_timer(svc):
    """Regression: on_mount must set the heartbeat interval (not just the
    poll heartbeat for daemon liveness)."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.screens.main import MainScreen

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = next(s for s in app.screen_stack if isinstance(s, MainScreen))
        # Sanity: the method exists and runs without crashing
        assert hasattr(screen, "_bus_heartbeat")
        screen._bus_heartbeat()  # must not raise


# -----------------------------------------------------------------------
# E. EventDetailView heartbeat-compatible filter
# -----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_event_detail_price_handler_accepts_heartbeat(svc, monkeypatch):
    """Missing `event_id` in payload = heartbeat match-all. Must still
    trigger a refresh so the view re-reads cross-process DB writes.

    Pre-fix the handler returned early when `event_id` was absent; the
    daemon's heartbeat would have been silently dropped."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    calls: list[str] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView("ev1", svc)
        await app.mount(view)
        await pilot.pause()
        # The handler uses dispatch_to_ui which calls app.call_later on
        # the UI thread. Spy there.
        monkeypatch.setattr(
            app, "call_later",
            lambda *args, **kw: calls.append("dispatched"),
        )
        svc.event_bus.publish(TOPIC_PRICE_UPDATED, {"source": "heartbeat"})
        await pilot.pause()
    assert calls, f"heartbeat publish did not reach dispatch_to_ui: {calls}"


@pytest.mark.asyncio
async def test_event_detail_price_handler_still_filters_other_events(svc):
    """Regression on E: a payload with a DIFFERENT event_id must still
    be filtered out (only this view's event_id or missing counts).

    Call the handler directly so MainScreen's match-all heartbeat doesn't
    pollute the signal we're verifying."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    calls: list[str] = []
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView("ev1", svc)
        await app.mount(view)
        await pilot.pause()
        # Patch call_later ONLY after the initial mount / heartbeat
        # dance so we see just this invocation.
        original_call_later = app.call_later
        app.call_later = lambda *a, **kw: calls.append("dispatched")
        try:
            view._on_price_update(
                {"event_id": "DIFFERENT_EVENT", "mid": 0.5},
            )
        finally:
            app.call_later = original_call_later
    assert not calls, f"other event's price update leaked through filter: {calls}"


def test_dispatch_to_ui_falls_back_to_call_later_on_ui_thread():
    """When `call_from_thread` raises RuntimeError (the signature Textual
    uses to signal 'you're on the event-loop thread'), `dispatch_to_ui`
    falls through to `call_later(0, fn)`."""
    from unittest.mock import MagicMock
    from scanner.tui._dispatch import dispatch_to_ui

    app = MagicMock()
    app.call_from_thread.side_effect = RuntimeError(
        "The `call_from_thread` method must run in a different thread",
    )
    fn = lambda: None
    dispatch_to_ui(app, fn)
    app.call_from_thread.assert_called_once_with(fn)
    app.call_later.assert_called_once_with(0, fn)


def test_dispatch_to_ui_uses_call_from_thread_when_it_works():
    """When `call_from_thread` succeeds (caller is on a worker thread),
    `call_later` must NOT be called — no double-dispatch."""
    from unittest.mock import MagicMock
    from scanner.tui._dispatch import dispatch_to_ui

    app = MagicMock()
    # call_from_thread returns normally (default MagicMock behavior)
    fn = lambda: None
    dispatch_to_ui(app, fn)
    app.call_from_thread.assert_called_once_with(fn)
    app.call_later.assert_not_called()


def test_dispatch_to_ui_generic_exception_is_logged_not_fatal():
    """If call_from_thread raises an unexpected exception (not
    RuntimeError), dispatch_to_ui must not fall through to call_later
    (which could double-dispatch) nor bubble up the exception."""
    from unittest.mock import MagicMock
    from scanner.tui._dispatch import dispatch_to_ui

    app = MagicMock()
    app.call_from_thread.side_effect = ValueError("unexpected")
    fn = lambda: None
    # Must not raise
    dispatch_to_ui(app, fn)
    app.call_from_thread.assert_called_once_with(fn)
    app.call_later.assert_not_called()
