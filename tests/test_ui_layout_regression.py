"""CSS-layout regression guards.

The widget tests in test_trade_dialog_widget.py / test_wallet_view.py query
by ID, which catches logic bugs but NOT layout bugs (a widget can be in the
DOM with `region.height == 0` — present in the tree, invisible to users).
These tests assert that critical widgets actually get rendered with
non-zero size at a realistic terminal width.

Motivated by v0.6.0 bug: Buy/Sell tab content collapsed to zero height
because TabbedContent's inner ContentSwitcher inherited `height: 1fr`
from an `auto`-height parent.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from textual.app import App
from textual.screen import Screen
from textual.widgets import Button

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, get_event_markets, upsert_event, upsert_market
from scanner.tui.service import ScanService
from scanner.tui.views.trade_dialog import TradeDialog
from scanner.tui.views.wallet import WalletView
from scanner.tui.views.wallet_modals import TopupModal, WithdrawModal

_REALISTIC_SIZE = (100, 30)  # typical laptop terminal


def _seed(tmp_path, *, buy_yes: bool = False, buy_no: bool = False) -> ScanService:
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="e1", title="T", updated_at="t"),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1", event_id="e1", question="Q",
            clob_token_id_yes="a", clob_token_id_no="b",
            yes_price=0.5, no_price=0.5, updated_at="t",
        ),
        db,
    )
    svc = ScanService(config=ScannerConfig(), db=db)
    if buy_yes or buy_no:
        with patch("scanner.core.trade_engine.TradeEngine._fetch_live_price", return_value=0.5):
            if buy_yes:
                svc.execute_buy(market_id="m1", side="yes", shares=10.0)
            if buy_no:
                svc.execute_buy(market_id="m1", side="no", shares=5.0)
    return svc


class _Host(App):
    def __init__(self, make_screen) -> None:
        super().__init__()
        self._make_screen = make_screen

    def on_mount(self) -> None:
        self.push_screen(self._make_screen())


class _HostScreen(Screen):
    def __init__(self, view) -> None:
        super().__init__()
        self._view = view

    def compose(self):
        yield self._view

    def refresh_sidebar_counts(self):
        pass


@pytest.mark.asyncio
async def test_trade_dialog_buy_action_buttons_render_with_height(tmp_path):
    """Guard: 买 YES / 买 NO buttons must render with non-zero height.

    Catches the TabbedContent-collapse bug where pane content was in DOM
    but had region.height == 0.
    """
    svc = _seed(tmp_path)
    markets = get_event_markets("e1", svc.db)

    host = _Host(lambda: TradeDialog("e1", markets, svc, default_tab="buy"))
    async with host.run_test(size=_REALISTIC_SIZE) as pilot:
        await pilot.pause()
        dialog = host.screen
        yes_btn = dialog.query_one("#btn-buy-yes", Button)
        no_btn = dialog.query_one("#btn-buy-no", Button)
        assert yes_btn.region.height > 0, "买 YES button collapsed to zero height"
        assert no_btn.region.height > 0, "买 NO button collapsed to zero height"
        # And the label must be the price-enriched one set by _refresh_button_labels.
        assert "YES" in str(yes_btn.label)
        assert "¢" in str(yes_btn.label)


@pytest.mark.asyncio
async def test_trade_dialog_sell_button_renders_with_label_and_height(tmp_path):
    """Guard: 卖出 button must render visibly (not just be in the DOM)."""
    svc = _seed(tmp_path, buy_yes=True)
    markets = get_event_markets("e1", svc.db)

    host = _Host(lambda: TradeDialog("e1", markets, svc, default_tab="sell"))
    async with host.run_test(size=_REALISTIC_SIZE) as pilot:
        await pilot.pause()
        dialog = host.screen
        sell_btn = dialog.query_one("#btn-sell", Button)
        assert sell_btn.region.height > 0, "卖出 button collapsed to zero height"
        # Label should include the side after the first refresh.
        assert "YES" in str(sell_btn.label)


@pytest.mark.asyncio
async def test_trade_dialog_sell_radio_fits_both_sides(tmp_path):
    """Guard: if both YES and NO positions exist, the radio must show both."""
    svc = _seed(tmp_path, buy_yes=True, buy_no=True)
    markets = get_event_markets("e1", svc.db)

    host = _Host(lambda: TradeDialog("e1", markets, svc, default_tab="sell"))
    async with host.run_test(size=_REALISTIC_SIZE) as pilot:
        await pilot.pause()
        dialog = host.screen
        from textual.widgets import RadioButton
        radios = list(dialog.query_one("#sell-side-radio").query(RadioButton))
        assert len(radios) == 2, f"expected 2 radio options, got {len(radios)}"
        # Both must have non-zero rendered height — not clipped by max-height.
        for r in radios:
            assert r.region.height > 0, f"radio button {r.label} collapsed"


@pytest.mark.asyncio
async def test_topup_modal_amount_row_is_not_stretched(tmp_path):
    """Guard: anonymous Horizontal containers must be height:auto not 1fr.

    Previously this row defaulted to 1fr and pushed quick-buttons + confirm
    button off screen on small terminals.
    """
    svc = _seed(tmp_path)

    host = _Host(lambda: TopupModal(svc))
    async with host.run_test(size=_REALISTIC_SIZE) as pilot:
        await pilot.pause()
        modal = host.screen
        # Amount input must fit in a single-row-ish Horizontal (allow a couple of
        # rows for padding), not stretch to fill available space.
        amount_input = modal.query_one("#amount")
        assert amount_input.region.height <= 4, (
            f"amount input unexpectedly tall: {amount_input.region.height}"
        )
        # Confirm button must be visible on screen.
        ok_btn = modal.query_one("#confirm", Button)
        assert ok_btn.region.height > 0


@pytest.mark.asyncio
async def test_withdraw_modal_amount_row_is_not_stretched(tmp_path):
    svc = _seed(tmp_path)
    host = _Host(lambda: WithdrawModal(svc))
    async with host.run_test(size=_REALISTIC_SIZE) as pilot:
        await pilot.pause()
        modal = host.screen
        amount_input = modal.query_one("#amount")
        assert amount_input.region.height <= 4
        ok_btn = modal.query_one("#confirm", Button)
        assert ok_btn.region.height > 0


@pytest.mark.asyncio
async def test_wallet_view_ledger_and_reset_button_visible(tmp_path):
    """Guard: WalletView ledger + reset button both render."""
    svc = _seed(tmp_path)
    host = _Host(lambda: _HostScreen(WalletView(svc)))
    async with host.run_test(size=_REALISTIC_SIZE) as pilot:
        await pilot.pause()
        view = host.screen.query_one(WalletView)
        from textual.widgets import DataTable
        table = view.query_one("#wallet-table", DataTable)
        reset_btn = view.query_one("#reset-btn", Button)
        assert table.region.height > 0
        assert reset_btn.region.height > 0
