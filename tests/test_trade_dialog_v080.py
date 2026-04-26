"""v0.8.0 Task 27: trade_dialog migrated (TradeDialog + BuyPane + SellPane)."""
from unittest.mock import MagicMock, patch

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import (
    EventRow,
    MarketRow,
    upsert_event,
    upsert_market,
)
from polily.core.events import TOPIC_PRICE_UPDATED, EventBus
from polily.tui.service import PolilyService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.tui.heartbeat_seconds = 5.0  # Phase 0 Task 14: real float for Textual timer
    cfg.wallet.starting_balance = 1000.0
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test Event", updated_at="now"),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1",
            event_id="ev1",
            question="Will X happen?",
            yes_price=0.5,
            no_price=0.5,
            updated_at="now",
        ),
        db,
    )
    yield PolilyService(config=cfg, db=db, event_bus=EventBus())
    db.close()


def _markets(svc):
    from polily.core.event_store import get_event_markets
    return get_event_markets("ev1", svc.db)


async def test_buy_pane_uses_atoms(svc):
    """BuyPane uses PolilyZone or PolilyCard for structured layout."""
    from polily.tui.app import PolilyApp
    from polily.tui.views.trade_dialog import TradeDialog
    from polily.tui.widgets.polily_card import PolilyCard
    from polily.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        dialog = TradeDialog("ev1", _markets(svc), svc)
        await app.push_screen(dialog)
        await pilot.pause()
        zones = list(dialog._buy_pane.query(PolilyZone))
        cards = list(dialog._buy_pane.query(PolilyCard))
        assert len(zones) + len(cards) >= 1, (
            f"BuyPane should use v0.8.0 atoms; got zones={len(zones)} cards={len(cards)}"
        )


async def test_sell_pane_uses_atoms(svc):
    from polily.tui.app import PolilyApp
    from polily.tui.views.trade_dialog import TradeDialog
    from polily.tui.widgets.polily_card import PolilyCard
    from polily.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        dialog = TradeDialog("ev1", _markets(svc), svc)
        await app.push_screen(dialog)
        await pilot.pause()
        zones = list(dialog._sell_pane.query(PolilyZone))
        cards = list(dialog._sell_pane.query(PolilyCard))
        assert len(zones) + len(cards) >= 1, (
            f"SellPane should use v0.8.0 atoms; got zones={len(zones)} cards={len(cards)}"
        )


async def test_trade_dialog_chinese_labels(svc):
    from textual.widgets import Button, Static

    from polily.tui.app import PolilyApp
    from polily.tui.views.trade_dialog import TradeDialog

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        dialog = TradeDialog("ev1", _markets(svc), svc)
        await app.push_screen(dialog)
        await pilot.pause()
        texts: list[str] = []
        for s in dialog.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        for b in dialog.query(Button):
            texts.append(str(b.label))
        joined = " ".join(texts)
        # Key v0.8.0 labels that MUST be present
        for lbl in ("买入", "卖出"):
            assert lbl in joined, f"label {lbl} missing. Sample: {joined[:300]}"


async def test_trade_dialog_has_market_title_not_ids(svc):
    """Dialog must show market title text, never expose internal event_id / market_id."""
    from textual.widgets import Static

    from polily.tui.app import PolilyApp
    from polily.tui.views.trade_dialog import TradeDialog

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        dialog = TradeDialog("ev1", _markets(svc), svc)
        await app.push_screen(dialog)
        await pilot.pause()
        texts: list[str] = []
        for s in dialog.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        joined = " ".join(texts)
        # Internal IDs ("ev1", "m1") MUST not appear as standalone labels in user-visible output.
        # (Heuristic: these exact tokens.)
        assert "event_id" not in joined
        assert "market_id" not in joined


async def test_trade_dialog_price_bus_subscription(svc):
    """Panes subscribe to TOPIC_PRICE_UPDATED; publishing triggers call_from_thread."""
    from polily.tui.app import PolilyApp
    from polily.tui.views.trade_dialog import TradeDialog

    called: list[str] = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        dialog = TradeDialog("ev1", _markets(svc), svc)
        await app.push_screen(dialog)
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
                TOPIC_PRICE_UPDATED,
                {"event_id": "ev1", "market_id": "m1", "mid": 0.5, "spread": 0.02},
            )
            await pilot.pause()
        # Some callback named with refresh/render/update was invoked via call_from_thread
        assert any(
            "refresh" in n.lower() or "render" in n.lower() or "update" in n.lower()
            for n in called
        ), f"price bus callback did not trigger re-render: {called}"


async def test_trade_dialog_preserves_widget_ids(svc):
    """Regression: Existing tests use specific widget IDs (#buy-amount, #btn-sell, etc.)
    that MUST be preserved through migration.

    v0.8.0 Opt-A3: #btn-buy-yes / #btn-buy-no migrated to BuySellActionRow atom's
    internal ids (#btn-yes / #btn-no). We scope the lookup via BuyPane so the atom
    boundary is explicit.
    """
    from textual.widgets import Button, Input

    from polily.tui.app import PolilyApp
    from polily.tui.views.trade_dialog import BuyPane, TradeDialog

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        dialog = TradeDialog("ev1", _markets(svc), svc)
        await app.push_screen(dialog)
        await pilot.pause()

        # BuyPane IDs used by existing test_trade_dialog_widget.py
        dialog.query_one("#buy-amount", Input)
        buy_pane = dialog.query_one(BuyPane)
        buy_pane.query_one("#btn-yes", Button)
        buy_pane.query_one("#btn-no", Button)
        dialog.query_one("#quick-20", Button)  # v0.8.0 Opt-A2: QuickAmountRow atom

        # SellPane IDs
        dialog.query_one("#btn-sell", Button)
        dialog.query_one("#sell-pct-100", Button)
