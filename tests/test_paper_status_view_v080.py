"""v0.8.0 Task 23: paper_status view migrated to atoms + events + i18n."""
import contextlib
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import DataTable, Static

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.events import (
    TOPIC_POSITION_UPDATED,
    TOPIC_WALLET_UPDATED,
    EventBus,
)
from scanner.tui.service import PolilyService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "p.db")
    upsert_event(
        EventRow(
            event_id="ev1",
            title="Paper Event",
            structure_score=75.0,
            market_count=1,
            updated_at="now",
        ),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1",
            event_id="ev1",
            question="Will Paper happen?",
            clob_token_id_yes="tok_y",
            clob_token_id_no="tok_n",
            yes_price=0.5,
            updated_at="now",
        ),
        db,
    )
    # v0.8.0: PolilyService.execute_buy/sell require auto_monitor=1.
    from scanner.core.monitor_store import upsert_event_monitor
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    s = PolilyService(config=cfg, db=db, event_bus=EventBus())
    yield s
    db.close()


def _seed_position(svc):
    """Seed one open YES position for paper_status to display."""
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)


async def test_paper_status_uses_polily_zones(svc):
    """Verify PolilyZone atom wraps the portfolio list."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.paper_status import PaperStatusView
    from scanner.tui.widgets.polily_zone import PolilyZone

    _seed_position(svc)
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 1, f"expected PolilyZone(s), got {len(zones)}"


async def test_paper_status_chinese_labels(svc):
    """Core Chinese label appears somewhere in rendered view."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.paper_status import PaperStatusView

    _seed_position(svc)
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
        await app.mount(view)
        await pilot.pause()
        texts: list[str] = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        tables = list(view.query(DataTable))
        for t in tables:
            for col in t.columns.values():
                texts.append(str(getattr(col, "label", "")))
            for row_key in t.rows:
                for col_key in t.columns:
                    with contextlib.suppress(Exception):
                        texts.append(str(t.get_cell(row_key, col_key)))
        joined = " ".join(texts)
        found = any(lbl in joined for lbl in ("持仓", "余额", "已实现", "浮动", "事件"))
        assert found, f"no Chinese label found. Sample: {joined[:300]}"


async def test_paper_status_wallet_bus_callback(svc):
    """TOPIC_WALLET_UPDATED publish → view re-renders via call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.paper_status import PaperStatusView

    _seed_position(svc)
    called: list[str] = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
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
                {"balance": 150.0, "source": "test"},
            )
            await pilot.pause()
        assert any(
            "render" in n.lower() or "refresh" in n.lower() or "update" in n.lower()
            for n in called
        ), f"wallet bus callback did not trigger re-render: {called}"


async def test_paper_status_position_bus_callback(svc):
    """TOPIC_POSITION_UPDATED publish → view re-renders via call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.paper_status import PaperStatusView

    _seed_position(svc)
    called: list[str] = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
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
                TOPIC_POSITION_UPDATED,
                {"market_id": "m1", "side": "yes", "size": 20.0},
            )
            await pilot.pause()
        assert any(
            "render" in n.lower() or "refresh" in n.lower() or "update" in n.lower()
            for n in called
        ), f"position bus callback did not trigger re-render: {called}"


async def test_paper_status_no_internal_ids_leaked(svc):
    """Row cells should show title, not internal market_id / event_id."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.paper_status import PaperStatusView

    _seed_position(svc)
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
        await app.mount(view)
        await pilot.pause()

        texts: list[str] = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        tables = list(view.query(DataTable))
        for t in tables:
            for row_key in t.rows:
                for col_key in t.columns:
                    with contextlib.suppress(Exception):
                        texts.append(str(t.get_cell(row_key, col_key)))

        joined = " ".join(texts)
        # Market question (human-readable label) shown, not internal IDs.
        assert "Paper" in joined, (
            f"market question missing from view. Sample: {joined[:400]}"
        )
        # Internal IDs must not be surfaced as visible cell text.
        # (They may remain as DataTable row_keys for navigation.)
        assert "ev1" not in joined, (
            f"internal event_id leaked to UI. Sample: {joined[:400]}"
        )
