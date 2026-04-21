"""POC tests for `once_per_tick` — per-instance, per-method coalescing
of bus-driven refreshes within a single event-loop tick.

Inspired by React 18's automatic batching / `useRef + queueMicrotask`
pattern: multiple synchronous bus events in the same tick coalesce
into a single refresh next tick. Prevents `_render_all` from running
N times per heartbeat when a view subscribes to N topics.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.events import (
    TOPIC_POSITION_UPDATED,
    TOPIC_PRICE_UPDATED,
    EventBus,
)
from scanner.core.monitor_store import upsert_event_monitor


def test_same_instance_three_rapid_calls_coalesce_to_one():
    """3 sync calls on the same instance within a tick → 1 execution."""
    from scanner.tui._dispatch import once_per_tick

    class View:
        def __init__(self):
            self.call_count = 0
            self.app = MagicMock()
            # Simulate "UI thread" — call_from_thread raises as Textual does.
            self.app.call_from_thread.side_effect = RuntimeError("on UI thread")
            # call_later is the fallback; store the scheduled fn so we can run it.
            self.scheduled = []
            self.app.call_later.side_effect = lambda delay, fn: self.scheduled.append(fn)

        @once_per_tick
        def refresh(self):
            self.call_count += 1

    v = View()
    v.refresh()
    v.refresh()
    v.refresh()
    # Three calls, ONE scheduled execution.
    assert len(v.scheduled) == 1, \
        f"expected 1 scheduled refresh, got {len(v.scheduled)}"
    # Simulate next-tick: run the scheduled callback.
    v.scheduled[0]()
    assert v.call_count == 1, f"expected 1 actual refresh, got {v.call_count}"


def test_across_tick_boundary_allows_second_refresh():
    """After a tick runs, the next bus event schedules fresh."""
    from scanner.tui._dispatch import once_per_tick

    class View:
        def __init__(self):
            self.call_count = 0
            self.app = MagicMock()
            self.app.call_from_thread.side_effect = RuntimeError("on UI thread")
            self.scheduled: list = []
            self.app.call_later.side_effect = lambda delay, fn: self.scheduled.append(fn)

        @once_per_tick
        def refresh(self):
            self.call_count += 1

    v = View()
    v.refresh()
    v.refresh()
    assert len(v.scheduled) == 1
    # Tick runs — scheduled callback executes, clearing the flag
    v.scheduled[0]()
    assert v.call_count == 1
    # After tick: next bus event must schedule a new refresh
    v.refresh()
    assert len(v.scheduled) == 2, \
        f"after tick boundary, 2nd call should schedule; got {len(v.scheduled)}"
    v.scheduled[1]()
    assert v.call_count == 2


def test_different_instances_do_not_share_state():
    """Per-instance flag: view A's pending refresh must not block view B."""
    from scanner.tui._dispatch import once_per_tick

    class View:
        def __init__(self):
            self.call_count = 0
            self.app = MagicMock()
            self.app.call_from_thread.side_effect = RuntimeError("on UI thread")
            self.scheduled: list = []
            self.app.call_later.side_effect = lambda delay, fn: self.scheduled.append(fn)

        @once_per_tick
        def refresh(self):
            self.call_count += 1

    a = View()
    b = View()
    a.refresh()
    b.refresh()
    assert len(a.scheduled) == 1, "A should have its own scheduled refresh"
    assert len(b.scheduled) == 1, "B should have its own scheduled refresh"


def test_worker_thread_path_also_coalesces():
    """From a worker thread dispatch goes through `call_from_thread` — the
    dedup flag must still apply before the scheduling call is made."""
    from scanner.tui._dispatch import once_per_tick

    class View:
        def __init__(self):
            self.app = MagicMock()
            # call_from_thread succeeds (simulating worker thread)
            self.scheduled: list = []
            self.app.call_from_thread.side_effect = lambda fn: self.scheduled.append(fn)

        @once_per_tick
        def refresh(self):
            pass

    v = View()
    v.refresh()
    v.refresh()
    v.refresh()
    # Even on worker-thread dispatch path, flag prevents duplicate schedules.
    assert len(v.scheduled) == 1, \
        f"worker-thread path must also dedup; got {len(v.scheduled)}"


def test_decorator_preserves_method_name_and_docstring():
    """Smoke: functools.wraps should preserve the wrapped function's
    identity so debugger / traceback still shows the original name."""
    from scanner.tui._dispatch import once_per_tick

    class View:
        @once_per_tick
        def refresh_data(self):
            """Original docstring."""
            pass

    assert View.refresh_data.__name__ == "refresh_data"
    assert View.refresh_data.__doc__ == "Original docstring."


# -------------------------------------------------------------------------
# End-to-end: EventDetailView under a simulated heartbeat
# -------------------------------------------------------------------------


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test", slug="test-slug", updated_at="now"),
        db,
    )
    upsert_market(
        MarketRow(market_id="m1", event_id="ev1", question="Q",
                  yes_price=0.5, updated_at="now"),
        db,
    )
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    from scanner.tui.service import ScanService
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


async def _assert_view_coalesces(
    svc, monkeypatch, view_cls, topics, view_kwargs=None,
):
    """Shared helper: mount `view_cls` in a BARE host app (no MainScreen
    so no background view subscribers pollute the call_later counter),
    publish every topic, assert call_later is invoked exactly once.
    """
    from textual.app import App as TextualApp
    from textual.app import ComposeResult

    view_kwargs = view_kwargs or {"service": svc}

    dispatch_count = 0

    class _Host(TextualApp):
        def compose(self) -> ComposeResult:
            yield view_cls(**view_kwargs)

    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        view = host.query_one(view_cls)
        # Drain the initial on_mount dispatch (if any).
        await pilot.pause(0.05)
        # Reset per-view decorator flags.
        for attr in list(vars(view)):
            if attr.startswith("_once_per_tick__"):
                setattr(view, attr, False)

        original_call_later = host.call_later
        def spy(*args, **kwargs):
            nonlocal dispatch_count
            if len(args) >= 2 and args[0] == 0 and callable(args[1]):
                dispatch_count += 1
            return original_call_later(*args, **kwargs)
        monkeypatch.setattr(host, "call_later", spy)

        for topic in topics:
            svc.event_bus.publish(topic, {"source": "heartbeat"})

    assert dispatch_count == 1, (
        f"{view_cls.__name__}: {len(topics)} topics → expected 1 "
        f"dispatch (coalesced), got {dispatch_count}"
    )


@pytest.mark.asyncio
async def test_monitor_list_coalesces_heartbeat_fan_out(svc, monkeypatch):
    """MonitorListView subscribes to 3 topics — heartbeat pre-fix fired
    _render_all 3×. Now coalesced to 1."""
    from scanner.core.events import (
        TOPIC_MONITOR_UPDATED,
        TOPIC_PRICE_UPDATED,
        TOPIC_SCAN_UPDATED,
    )
    from scanner.tui.views.monitor_list import MonitorListView
    await _assert_view_coalesces(
        svc, monkeypatch, MonitorListView,
        [TOPIC_MONITOR_UPDATED, TOPIC_PRICE_UPDATED, TOPIC_SCAN_UPDATED],
    )


@pytest.mark.asyncio
async def test_paper_status_coalesces_heartbeat_fan_out(svc, monkeypatch):
    """PaperStatusView subscribes to 3 topics (WALLET+POSITION+PRICE)."""
    from scanner.core.events import (
        TOPIC_POSITION_UPDATED,
        TOPIC_PRICE_UPDATED,
        TOPIC_WALLET_UPDATED,
    )
    from scanner.tui.views.paper_status import PaperStatusView
    await _assert_view_coalesces(
        svc, monkeypatch, PaperStatusView,
        [TOPIC_WALLET_UPDATED, TOPIC_POSITION_UPDATED, TOPIC_PRICE_UPDATED],
    )


@pytest.mark.asyncio
async def test_wallet_coalesces_heartbeat_fan_out(svc, monkeypatch):
    """WalletView subscribes to 2 topics (WALLET+POSITION)."""
    from scanner.core.events import TOPIC_POSITION_UPDATED, TOPIC_WALLET_UPDATED
    from scanner.tui.views.wallet import WalletView
    await _assert_view_coalesces(
        svc, monkeypatch, WalletView,
        [TOPIC_WALLET_UPDATED, TOPIC_POSITION_UPDATED],
    )


@pytest.mark.asyncio
async def test_event_detail_coalesces_heartbeat_fan_out(svc, monkeypatch):
    """Heartbeat fires PRICE + POSITION back-to-back in the same sync
    stack. EventDetailView subscribes to both, so pre-coalescing this
    triggered `refresh_data` twice. With @once_per_tick it schedules
    dispatch once.

    Proof point: count how many times `app.call_later` is invoked with
    the decorator's `run` callable. Pre-fix: 2. Post-fix: 1.
    """
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    dispatch_count = 0
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView("ev1", svc)
        await app.mount(view)
        await pilot.pause()

        original_call_later = app.call_later
        def spy(*args, **kwargs):
            nonlocal dispatch_count
            # Count only heartbeat dispatches: call_later(0, callable).
            # Textual's internal uses other signatures (callable only, etc.)
            if len(args) >= 2 and args[0] == 0 and callable(args[1]):
                dispatch_count += 1
            return original_call_later(*args, **kwargs)
        monkeypatch.setattr(app, "call_later", spy)

        # Simulate heartbeat: PRICE + POSITION fan-out in same sync stack.
        svc.event_bus.publish(TOPIC_PRICE_UPDATED, {"source": "heartbeat"})
        svc.event_bus.publish(TOPIC_POSITION_UPDATED, {"source": "heartbeat"})
        await pilot.pause()

    assert dispatch_count == 1, \
        f"2 bus events in same tick should coalesce to 1 dispatch; got {dispatch_count}"
