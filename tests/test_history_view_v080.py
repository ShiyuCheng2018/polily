"""v0.8.0 Task 25: history view migrated to atoms + events + i18n."""
from unittest.mock import MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.events import TOPIC_WALLET_UPDATED, EventBus
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "h.db")
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


async def test_history_uses_polily_zone(svc):
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.history import HistoryView
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = HistoryView(svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 1


async def test_history_chinese_labels(svc):
    from textual.widgets import Static

    from scanner.tui.app import PolilyApp
    from scanner.tui.views.history import HistoryView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = HistoryView(svc)
        await app.mount(view)
        await pilot.pause()
        texts = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        joined = " ".join(texts)
        found = any(lbl in joined for lbl in ("历史", "已实现", "已完成", "交易", "盈亏"))
        assert found, f"no Chinese label found. Sample: {joined[:200]}"


async def test_history_bus_callback_if_subscribed(svc):
    """If view subscribes to TOPIC_WALLET_UPDATED, callback must use call_from_thread.

    This test is soft — if the view intentionally doesn't subscribe (static
    history, needs manual `r` refresh), passing is fine. But if subscription
    exists, verify threading pattern.
    """
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.history import HistoryView

    called = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = HistoryView(svc)
        await app.mount(view)
        await pilot.pause()
        # v0.8.0 dispatch_to_ui picks call_later on UI thread or
        # call_from_thread on worker — patch both.
        def spy_ct(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))

        def spy_cl(*args, **kw):
            if len(args) >= 2:
                called.append(getattr(args[1], "__name__", str(args[1])))

        with patch.object(app, "call_from_thread", side_effect=spy_ct), \
             patch.object(app, "call_later", side_effect=spy_cl):
            svc.event_bus.publish(
                TOPIC_WALLET_UPDATED,
                {"balance": 100.0, "source": "sell"},
            )
            await pilot.pause()
        # If called is non-empty, verify rendering-related intent. If empty,
        # view didn't subscribe — also valid; test passes trivially.
        if called:
            assert any(
                "render" in n.lower() or "refresh" in n.lower() or "update" in n.lower()
                for n in called
            ), f"subscribed but callback unclear: {called}"
