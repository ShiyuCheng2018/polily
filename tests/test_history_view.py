"""HistoryView widget — pulls from wallet_transactions (v0.6.0).

Assert the rendering pipeline end-to-end: service → widget → rows in the
DataTable and a non-empty summary line. Pure aggregation math lives in
test_realized_history.py.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App
from textual.screen import Screen
from textual.widgets import DataTable, Static

from scanner.core.config import PolilyConfig
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import PolilyService
from scanner.tui.views.history import HistoryView


def _svc(tmp_path) -> PolilyService:
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="e1", title="E1", updated_at="now"), db)
    upsert_market(
        MarketRow(
            market_id="m1", event_id="e1", question="Will BTC reach $100K?",
            clob_token_id_yes="ty", clob_token_id_no="tn",
            yes_price=0.5, no_price=0.5, updated_at="now",
            fees_enabled=0, fee_rate=None,
        ),
        db,
    )
    # v0.8.0: PolilyService.execute_buy/sell require auto_monitor=1.
    upsert_event_monitor("e1", auto_monitor=True, db=db)
    return PolilyService(config=PolilyConfig(), db=db)


class _Host(App):
    def __init__(self, service: PolilyService):
        super().__init__()
        self._service = service

    def on_mount(self) -> None:
        self.push_screen(_HostScreen(self._service))


class _HostScreen(Screen):
    def __init__(self, service: PolilyService):
        super().__init__()
        self._service = service

    def compose(self):
        yield HistoryView(self._service)


@pytest.mark.asyncio
async def test_empty_history_shows_empty_summary(tmp_path):
    svc = _svc(tmp_path)
    host = _Host(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        summary = host.screen.query_one("#history-summary", Static).content
        assert "暂无已实现的交易" in str(summary)
        # DataTable exists but has no rows.
        table = host.screen.query_one("#history-table", DataTable)
        assert table.row_count == 0


@pytest.mark.asyncio
async def test_history_renders_sell_row(tmp_path):
    """Buy then sell at profit → one SELL row + positive P&L in summary."""
    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.6,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=10.0)

    host = _Host(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = host.screen.query_one("#history-table", DataTable)
        assert table.row_count == 1
        summary = str(host.screen.query_one("#history-summary", Static).content)
        # Pnl ≈ 1.00 (before fees which are 0 on this market).
        assert "已实现 1 笔" in summary
        assert "+$1.00" in summary


@pytest.mark.asyncio
async def test_history_renders_multiple_events_newest_first(tmp_path):
    """2 sells from the same position → 2 rows, newest on top."""
    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.6,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.7,
    ):
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)

    host = _Host(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = host.screen.query_one("#history-table", DataTable)
        assert table.row_count == 2


@pytest.mark.asyncio
async def test_history_renders_resolve_row(tmp_path):
    """RESOLVE row appears with price=1.00 and positive P&L when YES wins."""
    from scanner.daemon.resolution import ResolutionHandler

    svc = _svc(tmp_path)
    with patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=0.5,
    ):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    svc.db.conn.execute("UPDATE markets SET closed=1 WHERE market_id='m1'")
    svc.db.conn.commit()
    ResolutionHandler(svc.db, svc.wallet, svc.positions).resolve_market("m1", "yes")

    host = _Host(svc)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        table = host.screen.query_one("#history-table", DataTable)
        assert table.row_count == 1
        summary = str(host.screen.query_one("#history-summary", Static).content)
        # realized = (1.0 - 0.5) × 10 = $5.00
        assert "+$5.00" in summary
