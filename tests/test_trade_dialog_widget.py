"""Widget integration tests for TradeDialog (Buy/Sell tabs).

Mounts the dialog on a minimal host App, exercises pilot interactions,
and asserts that the right PolilyService calls happen and the dismiss
payload reflects the action. Preview math is unit-tested in
test_trade_preview.py — these tests validate the WIRING (inputs →
buttons → service calls → dismiss).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import Button, Input, Static

from polily.core.config import PolilyConfig
from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.tui.service import PolilyService
from polily.tui.views.trade_dialog import BuyPane, TradeDialog


def _seed(
    tmp_path,
    *,
    fees_enabled: int = 1,
    fee_rate: float | None = 0.072,
):
    """Seed a crypto_fees_v2-style market by default so buy-flow tests
    exercise the fee path. Callers override to test fees-off markets.
    """
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="e1", title="BTC April", updated_at="now"),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1", event_id="e1", question="Will BTC reach $80K?",
            clob_token_id_yes="tok_yes", clob_token_id_no="tok_no",
            yes_price=0.50, no_price=0.50, updated_at="now",
            fees_enabled=fees_enabled, fee_rate=fee_rate,
        ),
        db,
    )
    # v0.8.0: PolilyService.execute_buy/sell require auto_monitor=1.
    from polily.core.monitor_store import upsert_event_monitor
    upsert_event_monitor("e1", auto_monitor=True, db=db)
    return PolilyService(config=PolilyConfig(), db=db)


class _Host(App):
    """Minimal app that pushes TradeDialog on mount."""

    def __init__(self, service, markets, default_tab: str = "buy") -> None:
        super().__init__()
        self._service = service
        self._markets = markets
        self._default_tab = default_tab
        self.dismiss_result: dict | None = None

    def on_mount(self) -> None:
        dialog = TradeDialog(
            "e1", self._markets, self._service, default_tab=self._default_tab,
        )

        def _on_dismiss(result: dict | None) -> None:
            self.dismiss_result = result

        self.push_screen(dialog, _on_dismiss)


def _mock_price(value: float):
    return patch(
        "polily.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=value,
    )


@pytest.mark.asyncio
async def test_buy_flow_dispatches_execute_buy_and_dismisses(tmp_path):
    """Type amount $20 → click 买 YES → execute_buy called, dismiss returns action=buy."""
    svc = _seed(tmp_path)
    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    with _mock_price(0.5):
        host = _Host(svc, market_rows)
        async with host.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = host.screen
            # Set amount to $20 (20 / 0.5 = 40 shares at YES 50¢).
            dialog.query_one("#buy-amount", Input).value = "20"
            await pilot.pause()
            dialog.query_one(BuyPane).query_one("#btn-yes", Button).press()
            await pilot.pause()

    assert host.dismiss_result is not None
    assert host.dismiss_result["action"] == "buy"
    assert host.dismiss_result["side"] == "yes"
    # 20 / 0.5 = 40 shares.
    assert host.dismiss_result["shares"] == pytest.approx(40.0)
    # Position should now exist.
    pos = svc.positions.get_position("m1", "yes")
    assert pos is not None
    assert pos["shares"] == pytest.approx(40.0)


@pytest.mark.asyncio
async def test_buy_quick_amount_fills_input(tmp_path):
    """Click [$20] quick button → amount input becomes '20'."""
    from textual.widgets import Button, Input

    svc = _seed(tmp_path)
    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    host = _Host(svc, market_rows)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        dialog = host.screen
        dialog.query_one("#quick-20", Button).press()
        await pilot.pause()
        assert dialog.query_one("#buy-amount", Input).value == "20"


@pytest.mark.asyncio
async def test_sell_flow_percent_then_sell_dispatches_execute_sell(tmp_path):
    """Pre-seed position → switch to Sell → click 100% → click 卖出 → execute_sell."""
    svc = _seed(tmp_path)
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=20.0)

    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    with _mock_price(0.6):
        host = _Host(svc, market_rows, default_tab="sell")
        async with host.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            dialog = host.screen
            dialog.query_one("#sell-pct-100", Button).press()
            await pilot.pause()
            dialog.query_one("#btn-sell", Button).press()
            await pilot.pause()

    assert host.dismiss_result is not None
    assert host.dismiss_result["action"] == "sell"
    assert host.dismiss_result["side"] == "yes"
    assert host.dismiss_result["shares"] == pytest.approx(20.0)
    # Position should be fully closed.
    assert svc.positions.get_position("m1", "yes") is None


@pytest.mark.asyncio
async def test_sell_empty_state_when_no_positions(tmp_path):
    """No positions on selected market → pct / shares / sell rows hidden; empty hint shown."""
    svc = _seed(tmp_path)
    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    host = _Host(svc, market_rows, default_tab="sell")
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        dialog = host.screen
        hint = dialog.query_one("#sell-empty-hint", Static).content
        assert "暂无持仓" in str(hint)
        pct_row = dialog.query_one("#sell-pct-row")
        shares_row = dialog.query_one("#sell-shares-row")
        action_row = dialog.query_one("#sell-action-row")
        assert pct_row.display is False
        assert shares_row.display is False
        assert action_row.display is False


@pytest.mark.asyncio
async def test_buy_disables_buttons_when_cash_insufficient(tmp_path):
    """Amount > wallet cash → YES/NO disabled + red warning."""
    svc = _seed(tmp_path)
    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    host = _Host(svc, market_rows)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        dialog = host.screen
        # Wallet seeded with $100; ask for $200.
        dialog.query_one("#buy-amount", Input).value = "200"
        await pilot.pause()
        buy_pane = dialog.query_one(BuyPane)
        yes_btn = buy_pane.query_one("#btn-yes", Button)
        no_btn = buy_pane.query_one("#btn-no", Button)
        assert yes_btn.disabled
        assert no_btn.disabled
        fee_line = dialog.query_one("#buy-fee-line", Static).content
        assert "余额不足" in str(fee_line)


@pytest.mark.asyncio
async def test_buy_buttons_re_enable_when_cash_becomes_sufficient(tmp_path):
    """Regression: insufficient → sufficient should clear disabled state."""
    svc = _seed(tmp_path)
    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    host = _Host(svc, market_rows)
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        dialog = host.screen
        amount = dialog.query_one("#buy-amount", Input)

        buy_pane = dialog.query_one(BuyPane)

        amount.value = "200"
        await pilot.pause()
        assert buy_pane.query_one("#btn-yes", Button).disabled

        amount.value = "10"
        await pilot.pause()
        assert not buy_pane.query_one("#btn-yes", Button).disabled
        assert not buy_pane.query_one("#btn-no", Button).disabled


@pytest.mark.asyncio
async def test_sell_preserves_selected_side_across_context_refresh(tmp_path):
    """Regression: SellPane periodic refresh must not stomp user's radio pick.

    Scenario: user has YES+NO positions → picks NO via radio → dialog's
    3s timer calls update_context with same positions → selection stays on NO.
    """
    svc = _seed(tmp_path)
    # Seed positions on BOTH sides of m1.
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="no", shares=5.0)

    from polily.core.event_store import get_event_markets
    market_rows = get_event_markets("e1", svc.db)

    host = _Host(svc, market_rows, default_tab="sell")
    async with host.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        dialog = host.screen
        sell_pane = dialog._sell_pane
        # Default selection comes from positions order — we just want the OTHER one.
        initial = sell_pane._selected_side
        other = "no" if initial == "yes" else "yes"

        # User switches via radio state mutation (equivalent to click).
        sell_pane._selected_side = other

        # Simulate periodic refresh — same position set, should NOT stomp selection.
        dialog._push_context_to_panes()
        await pilot.pause()
        assert sell_pane._selected_side == other

        # And again (hitting the "skip rebuild" path explicitly).
        dialog._push_context_to_panes()
        await pilot.pause()
        assert sell_pane._selected_side == other
