"""TradeDialog: modal with Buy/Sell tabs.

Buy flow: pick sub-market → enter USD amount → click 买 YES / 买 NO
  → ScanService.execute_buy with shares = amount / preview_price.
Sell flow: pick sub-market → pick side (if both held) → pick %/manual shares
  → ScanService.execute_sell.

Preview arithmetic (shares, fee, realized P&L) lives in `_trade_preview.py`
so the panels match exactly what TradeEngine charges, without duplicating
the fee curve.

Price-drift note: preview uses DB `yes_price`/`no_price` (updated by the
poll job, ~30s resolution). `TradeEngine.execute_buy/sell` re-fetches a
fresh CLOB price at execution time, so actual fill may deviate a cent or
two from the preview. The post-execution `notify(...)` shows the actual
fill price and fee, so users see any drift after the fact. For a paper
trader this is acceptable; no slippage guard is enforced.

v0.8.0 migration:
- BuyPane / SellPane wrap inputs in PolilyZone atoms (ICON_BUY / ICON_SELL)
- TradeDialog market header uses PolilyCard with KVRow for balance line
- EventBus subscription to TOPIC_PRICE_UPDATED replaces the 3s polling timer
- All widget IDs preserved (referenced by existing widget tests)
"""

from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    Button,
    Input,
    Label,
    RadioButton,
    RadioSet,
    Static,
    TabbedContent,
    TabPane,
)

from scanner.core.event_store import get_event_markets
from scanner.core.events import TOPIC_PRICE_UPDATED
from scanner.tui._dispatch import dispatch_to_ui
from scanner.tui.icons import ICON_BUY, ICON_MARKET, ICON_SELL, ICON_WALLET
from scanner.tui.views._trade_preview import (
    compute_buy_preview,
    compute_sell_preview,
    shares_from_pct,
)
from scanner.tui.widgets.amount_input import AmountInput
from scanner.tui.widgets.buy_sell_action_row import BuySellActionRow
from scanner.tui.widgets.field_row import FieldRow
from scanner.tui.widgets.polily_card import PolilyCard
from scanner.tui.widgets.polily_zone import PolilyZone
from scanner.tui.widgets.quick_amount_row import QuickAmountRow

_DIALOG_WIDTH = 100
_QUICK_AMOUNTS = [10, 20, 50]
_QUICK_PCTS = (25, 50, 75, 100)


class BuyPane(Widget):
    """Buy tab: USD input → live share/fee preview → YES/NO execute."""

    class BuyConfirmed(Message):
        def __init__(self, *, market_id: str, side: str, shares: float) -> None:
            super().__init__()
            self.market_id = market_id
            self.side = side
            self.shares = shares

    def __init__(self) -> None:
        super().__init__()
        self._market = None
        self._cash: float = 0.0
        self._positions_here: list[dict] = []  # positions on currently-selected market
        self._action_row = BuySellActionRow(side="buy")

    def compose(self) -> ComposeResult:
        with PolilyZone(title=f"{ICON_BUY} 买入", id="buy-zone"):
            yield Static("", id="buy-holding-line")
            yield FieldRow(
                label="金额",
                unit="$",
                input_widget=AmountInput(value="10", id="buy-amount"),
                helper="",
                helper_id="buy-preview",
                id="buy-amount-row",
            )
            yield Static("", id="buy-fee-line", classes="preview-secondary")
            yield QuickAmountRow(amounts=_QUICK_AMOUNTS)
            yield self._action_row

    def update_context(
        self, *, market, cash: float, positions_here: list[dict],
    ) -> None:
        self._market = market
        self._cash = cash
        self._positions_here = positions_here
        self._refresh()

    def on_amount_input_amount_changed(
        self, event: AmountInput.AmountChanged,
    ) -> None:
        if event.input_id == "buy-amount":
            self._refresh()

    def on_quick_amount_row_selected(
        self, event: QuickAmountRow.Selected,
    ) -> None:
        # AmountInput IS-A Input — querying via Input still finds it.
        self.query_one("#buy-amount", Input).value = str(event.amount)

    def on_buy_sell_action_row_pressed(
        self, event: BuySellActionRow.Pressed,
    ) -> None:
        """YES/NO button press from the atom — dispatch to execute."""
        if event.side == "buy":
            self._execute(event.outcome)

    # ----- internals -----

    def _parse_amount(self) -> float | None:
        v, valid, _ = self.query_one("#buy-amount", AmountInput).parse()
        return v if valid else None

    def _side_price(self, side: str) -> float | None:
        if self._market is None or self._market.yes_price is None:
            return None
        yes = self._market.yes_price
        if side == "yes":
            return yes if 0 < yes < 1 else None
        no = self._market.no_price or round(1 - yes, 4)
        return no if 0 < no < 1 else None

    def _refresh(self) -> None:
        if self._market is None:
            return
        self._refresh_holdings()
        self._refresh_button_labels()
        self._refresh_preview()

    def _refresh_holdings(self) -> None:
        line = self.query_one("#buy-holding-line", Static)
        if not self._positions_here:
            line.update("[dim]已持有: —[/dim]")
            return
        parts = []
        for p in self._positions_here:
            parts.append(
                f"{p['side'].upper()} {p['shares']:.1f}股 @ {p['avg_cost'] * 100:.1f}¢",
            )
        line.update("[dim]已持有:[/dim] " + " · ".join(parts))

    def _refresh_button_labels(self) -> None:
        yes_p = self._side_price("yes")
        no_p = self._side_price("no")
        # Atom owns label formatting + price-missing disable. The cash-insufficient
        # disable override is applied in _refresh_preview() below.
        self._action_row.update(yes_price=yes_p, no_price=no_p,
                                yes_disabled=False, no_disabled=False)

    def _refresh_preview(self) -> None:
        preview = self.query_one("#buy-preview", Static)
        fee_line = self.query_one("#buy-fee-line", Static)

        amount = self._parse_amount()
        yes_p = self._side_price("yes")
        no_p = self._side_price("no")

        if amount is None or (yes_p is None and no_p is None):
            preview.update("[dim]输入有效金额后显示折算[/dim]")
            fee_line.update("")
            return

        rows: list[str] = []
        max_cash_required = 0.0
        max_fee = 0.0
        for side_label, price in (("YES", yes_p), ("NO", no_p)):
            if price is None:
                continue
            try:
                p = compute_buy_preview(
                    amount_usd=amount, price=price,
                    fees_enabled=bool(getattr(self._market, "fees_enabled", False)),
                    fee_rate=getattr(self._market, "fee_rate", None),
                )
            except ValueError:
                continue
            rows.append(
                f"{side_label}→{p['shares']:.1f}股 赢${p['to_win']:.2f}",
            )
            max_cash_required = max(max_cash_required, p["cash_required"])
            max_fee = max(max_fee, p["fee"])

        preview.update("  ·  ".join(rows) if rows else "[dim]—[/dim]")

        # Insufficient-funds advisory (worst-case side).
        if max_cash_required > self._cash:
            fee_line.update(
                f"[red]余额不足[/red] · 手续费 ≈ ${max_fee:.2f} · 需 ${max_cash_required:.2f} / 有 ${self._cash:.2f}",
            )
            # Disable both sides — TradeEngine would reject anyway.
            self._action_row.update(yes_disabled=True, no_disabled=True)
        else:
            fee_line.update(f"[dim]手续费 ≈ ${max_fee:.2f}[/dim]")

    def _execute(self, side: str) -> None:
        amount = self._parse_amount()
        if amount is None:
            self.notify("请输入有效金额")
            return
        price = self._side_price(side)
        if price is None or self._market is None:
            self.notify("该方向价格不可用")
            return
        try:
            p = compute_buy_preview(
                amount_usd=amount, price=price,
                fees_enabled=bool(getattr(self._market, "fees_enabled", False)),
                fee_rate=getattr(self._market, "fee_rate", None),
            )
        except ValueError as e:
            self.notify(f"无法执行: {e}")
            return
        self.post_message(self.BuyConfirmed(
            market_id=self._market.market_id,
            side=side,
            shares=p["shares"],
        ))


class SellPane(Widget):
    """Sell tab: pick side (radio if multi-side) → % / manual shares → realized P&L."""

    class SellConfirmed(Message):
        def __init__(self, *, market_id: str, side: str, shares: float) -> None:
            super().__init__()
            self.market_id = market_id
            self.side = side
            self.shares = shares

    def __init__(self) -> None:
        super().__init__()
        self._market = None
        self._positions_here: list[dict] = []
        self._selected_side: str | None = None
        self._positions_sig: tuple | None = None  # change-detection for _rebuild_radio

    def compose(self) -> ComposeResult:
        with PolilyZone(title=f"{ICON_SELL} 卖出", id="sell-zone"):
            # No "持仓:" static label — the radio set is self-evident, saving a row.
            yield RadioSet(id="sell-side-radio")
            yield Static("", id="sell-empty-hint")
            with Horizontal(id="sell-pct-row"):
                yield Label("卖出比例", classes="field-label")
                for pct in _QUICK_PCTS:
                    yield Button(f"{pct}%", id=f"sell-pct-{pct}", classes="quick-btn")
            yield FieldRow(
                label="股数",
                input_widget=AmountInput(value="", id="sell-shares"),
                helper="",
                helper_id="sell-preview",
                id="sell-shares-row",
            )
            yield Static("", id="sell-pnl-line", classes="preview-secondary")
            with Horizontal(id="sell-action-row"):
                yield Button(
                    "卖出",
                    id="btn-sell",
                    variant="warning",
                    classes="trade-btn bold",
                )

    def update_context(
        self, *, market, positions_here: list[dict],
    ) -> None:
        """Push new market/positions into the pane.

        Idempotent w.r.t. unchanged positions: skips radio rebuild when the
        position set is identical, which prevents the 3s periodic refresh
        from silently reverting the user's radio pick back to first side.
        """
        self._market = market
        self._positions_here = positions_here

        # Preserve user's selection if the side is still held.
        held_sides = {p["side"] for p in positions_here}
        if self._selected_side not in held_sides:
            self._selected_side = positions_here[0]["side"] if positions_here else None

        # Cheap signature compare — rebuild radio only on real change.
        new_sig = tuple(
            (p["side"], round(p["shares"], 6), round(p["avg_cost"], 6))
            for p in positions_here
        )
        if new_sig != self._positions_sig:
            self._rebuild_radio()
            self._positions_sig = new_sig

        self._refresh()

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "sell-side-radio":
            return
        idx = event.radio_set.pressed_index
        if 0 <= idx < len(self._positions_here):
            self._selected_side = self._positions_here[idx]["side"]
            self._refresh()

    def on_amount_input_amount_changed(
        self, event: AmountInput.AmountChanged,
    ) -> None:
        if event.input_id == "sell-shares":
            self._refresh_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id is None:
            return
        if event.button.id.startswith("sell-pct-"):
            pct = int(event.button.id.replace("sell-pct-", ""))
            self._apply_pct(pct)
            return
        if event.button.id == "btn-sell":
            self._execute()

    # ----- internals -----

    def _current_position(self) -> dict | None:
        if self._selected_side is None:
            return None
        for p in self._positions_here:
            if p["side"] == self._selected_side:
                return p
        return None

    def _exit_price(self, side: str) -> float | None:
        """Exit price: YES→yes_price (ask proxy), NO→no_price (complementary)."""
        if self._market is None or self._market.yes_price is None:
            return None
        yes = self._market.yes_price
        if side == "yes":
            return yes if 0 < yes < 1 else None
        no = self._market.no_price or round(1 - yes, 4)
        return no if 0 < no < 1 else None

    def _parse_shares(self) -> float | None:
        v, valid, _ = self.query_one("#sell-shares", AmountInput).parse()
        return v if valid else None

    def _rebuild_radio(self) -> None:
        radio = self.query_one("#sell-side-radio", RadioSet)
        for btn in list(radio.query(RadioButton)):
            btn.remove()
        for p in self._positions_here:
            radio.mount(RadioButton(
                f"{p['side'].upper()}  {p['shares']:.1f}股 @ {p['avg_cost'] * 100:.1f}¢",
                value=(p["side"] == self._selected_side),
            ))

    def _apply_pct(self, pct: int) -> None:
        pos = self._current_position()
        if pos is None:
            return
        shares = shares_from_pct(holdings=pos["shares"], pct=pct)
        # Round to 4 decimals so inputs stay tidy.
        self.query_one("#sell-shares", Input).value = f"{shares:.4f}".rstrip("0").rstrip(".")

    def _refresh(self) -> None:
        self._refresh_empty_state()
        self._refresh_sell_button_label()
        self._refresh_preview()

    def _refresh_empty_state(self) -> None:
        hint = self.query_one("#sell-empty-hint", Static)
        radio = self.query_one("#sell-side-radio", RadioSet)
        pct_row = self.query_one("#sell-pct-row", Horizontal)
        shares_row = self.query_one("#sell-shares-row", Horizontal)
        action_row = self.query_one("#sell-action-row", Horizontal)
        pnl = self.query_one("#sell-pnl-line", Static)
        preview = self.query_one("#sell-preview", Static)

        if not self._positions_here:
            hint.update("[dim]该子市场暂无持仓。切到 '买入' tab 建仓。[/dim]")
            hint.display = True
            radio.display = False
            pct_row.display = False
            shares_row.display = False
            action_row.display = False
            pnl.update("")
            preview.update("")
            return

        hint.update("")
        hint.display = False  # collapse empty hint row when we have positions
        radio.display = True
        pct_row.display = True
        shares_row.display = True
        action_row.display = True

    def _refresh_sell_button_label(self) -> None:
        if self._selected_side is None:
            return
        price = self._exit_price(self._selected_side)
        btn = self.query_one("#btn-sell", Button)
        if price is None:
            btn.label = f"卖出 {self._selected_side.upper()} (价格不可用)"
            btn.disabled = True
        else:
            btn.label = f"卖出 {self._selected_side.upper()} @ {price * 100:.1f}¢"
            btn.disabled = False

    def _refresh_preview(self) -> None:
        preview = self.query_one("#sell-preview", Static)
        pnl_line = self.query_one("#sell-pnl-line", Static)
        if not self._positions_here:
            preview.update("")
            pnl_line.update("")
            return

        pos = self._current_position()
        shares = self._parse_shares()
        price = self._exit_price(self._selected_side) if self._selected_side else None

        if pos is None or shares is None or price is None:
            preview.update("[dim]选择比例或输入股数[/dim]")
            pnl_line.update("")
            return

        if shares > pos["shares"]:
            preview.update(f"[red]超出持仓 (有 {pos['shares']:.2f} 股)[/red]")
            pnl_line.update("")
            self.query_one("#btn-sell", Button).disabled = True
            return

        try:
            p = compute_sell_preview(
                shares=shares, price=price,
                fees_enabled=bool(getattr(self._market, "fees_enabled", False)),
                fee_rate=getattr(self._market, "fee_rate", None),
                avg_cost=pos["avg_cost"],
            )
        except ValueError:
            preview.update("[dim]输入无效[/dim]")
            pnl_line.update("")
            return

        preview.update(
            f"净到账 ${p['net_received']:.2f}  ·  手续费 ${p['fee']:.2f}",
        )
        pnl = p["realized_pnl"]
        color = "green" if pnl > 0 else "red" if pnl < 0 else "dim"
        sign = "+" if pnl > 0 else ""
        pnl_line.update(f"已实现盈亏: [{color}]{sign}${pnl:.2f}[/{color}]")
        # Re-enable button if we disabled it on over-sell before.
        self.query_one("#btn-sell", Button).disabled = False

    def _execute(self) -> None:
        pos = self._current_position()
        shares = self._parse_shares()
        if pos is None or shares is None:
            self.notify("请选择要卖出的股数")
            return
        if shares > pos["shares"]:
            self.notify(f"超出持仓 (有 {pos['shares']:.2f} 股)")
            return
        if self._market is None or self._selected_side is None:
            return
        self.post_message(self.SellConfirmed(
            market_id=self._market.market_id,
            side=self._selected_side,
            shares=shares,
        ))


class TradeDialog(ModalScreen[dict | None]):
    """Modal dialog for paper trade entry (Buy/Sell).

    v0.8.0: market info header uses PolilyCard; buy/sell tab panes wrap their
    inputs in PolilyZone atoms (BuyPane, SellPane). EventBus subscription to
    TOPIC_PRICE_UPDATED replaces the 3s polling timer — prices refresh as soon
    as the daemon publishes new prices.
    """

    DEFAULT_CSS = f"""
    TradeDialog {{
        align: center middle;
    }}
    TradeDialog #dialog-box {{
        width: {_DIALOG_WIDTH};
        height: auto;
        max-height: 100%;
        border: thick $primary;
        background: $surface;
        padding: 0 2;
    }}
    /* v0.8.0: explicit fixed height — auto resolves to 1fr in this nesting
       (Vertical inside dialog-box with align: center middle + max-height: 100%),
       which made header-card stretch and push everything else off-screen. */
    TradeDialog #header-card {{
        height: 5;
        margin: 0 0 1 0;
    }}
    TradeDialog #dialog-title {{
        width: 1fr;
    }}
    TradeDialog #balance-label {{
        width: auto;
        color: $accent;
    }}
    TradeDialog #market-radios {{
        height: auto;
        max-height: 8;
        padding: 0 0 1 0;
    }}
    TradeDialog .field-label {{
        width: 12;
        padding: 1 1 0 0;
    }}
    TradeDialog .preview {{
        padding: 1 0 0 1;
        width: 1fr;
    }}
    TradeDialog .preview-secondary {{
        padding: 0 0 1 13;
    }}
    TradeDialog #buy-amount, TradeDialog #sell-shares {{
        width: 14;
    }}
    TradeDialog .quick-btn {{
        min-width: 6;
        margin: 0 1 0 0;
    }}
    TradeDialog .trade-btn {{
        min-width: 20;
        margin: 0 1;
    }}
    TradeDialog #sell-action-row {{
        height: auto;
        align: center middle;
        padding: 1 0;
    }}
    TradeDialog #sell-pct-row {{
        height: auto;
        padding: 0 0 1 0;
    }}
    TradeDialog #buy-amount-row, TradeDialog #sell-shares-row {{
        height: auto;
        padding: 0 0 1 0;
    }}
    TradeDialog #sell-side-radio {{
        height: auto;
        max-height: 4;
    }}
    TradeDialog #sell-empty-hint {{
        height: auto;
        padding: 1 0;
    }}
    TradeDialog #btn-sell {{
        min-width: 28;
        height: 3;
        color: white;
    }}
    /* TabbedContent inside an auto-height parent must itself be auto or
       its inner ContentSwitcher collapses to zero (tab headers visible,
       pane content invisible). Same for BuyPane / SellPane widgets. */
    TradeDialog TabbedContent {{
        height: auto;
    }}
    TradeDialog TabbedContent ContentSwitcher {{
        height: auto;
    }}
    TradeDialog TabPane {{
        height: auto;
    }}
    TradeDialog BuyPane, TradeDialog SellPane {{
        height: auto;
    }}
    /* Panes own a single PolilyZone each — keep it auto-sized. */
    TradeDialog BuyPane > PolilyZone,
    TradeDialog SellPane > PolilyZone {{
        height: auto;
        margin: 0;
    }}
    """

    BINDINGS = [("escape", "dismiss_cancel", "取消")]

    def __init__(
        self,
        event_id: str,
        markets: list,
        service,
        default_tab: str = "buy",
    ) -> None:
        super().__init__()
        self.event_id = event_id
        self._markets = [m for m in markets if not m.closed and m.yes_price is not None]
        self._service = service
        self._default_tab = default_tab
        self._buy_pane = BuyPane()
        self._sell_pane = SellPane()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            # Header card: title + live balance. PolilyCard gives us a softer
            # secondary-bordered frame so the header doesn't compete visually
            # with the thick primary outer dialog border.
            with PolilyCard(id="header-card"):
                with Horizontal(id="dialog-header"):
                    yield Static(f"{ICON_MARKET} 交易", id="dialog-title", classes="bold")
                    yield Static("", id="balance-label", classes="bold")
            yield Static("子市场:", classes="field-label")
            with RadioSet(id="market-radios"):
                for i, m in enumerate(self._markets):
                    label = m.group_item_title or (m.question or "")[:30]
                    yes = f"{m.yes_price * 100:.1f}¢" if m.yes_price else "?"
                    no_raw = m.no_price or round(1 - (m.yes_price or 0), 4)
                    no = f"{no_raw * 100:.1f}¢"
                    yield RadioButton(f"{label}  Y:{yes} N:{no}", value=i == 0)
            with TabbedContent(initial=self._default_tab, id="tabs"):
                with TabPane("买入", id="buy"):
                    yield self._buy_pane
                with TabPane("卖出", id="sell"):
                    yield self._sell_pane

    def on_mount(self) -> None:
        self._refresh_balance()
        self._push_context_to_panes()
        # v0.8.0: subscribe to price bus for event-driven refresh.
        # Kept the 3s timer as a fallback for when the daemon isn't running
        # (e.g. ad-hoc TUI session without scheduler) — bus + timer coalesce
        # on the same refresh method.
        self._service.event_bus.subscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self._refresh_timer = self.set_interval(3, self._refresh_prices_periodic)

    def on_unmount(self) -> None:
        with contextlib.suppress(Exception):
            self._service.event_bus.unsubscribe(
                TOPIC_PRICE_UPDATED, self._on_price_update,
            )

    def _on_price_update(self, payload: dict) -> None:
        """Bus callback — thread-safe via dispatch_to_ui.

        Missing `event_id` = match-all heartbeat (MainScreen's bridge
        for cross-process daemon writes).
        """
        ev = payload.get("event_id")
        if ev is not None and ev != self.event_id:
            return
        dispatch_to_ui(self.app, self._refresh_prices_periodic)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id == "market-radios":
            self._push_context_to_panes()

    def on_buy_pane_buy_confirmed(self, event: BuyPane.BuyConfirmed) -> None:
        try:
            result = self._service.execute_buy(
                market_id=event.market_id,
                side=event.side,
                shares=event.shares,
            )
        except Exception as e:
            self.notify(f"买入失败: {e}", severity="error")
            return
        self.notify(
            f"买入成功: {event.side.upper()} {event.shares:.2f}股 "
            f"@ {result['price'] * 100:.1f}¢  手续费 ${result['fee']:.2f}",
        )
        self.dismiss({"action": "buy", **result, "side": event.side, "shares": event.shares})

    def on_sell_pane_sell_confirmed(self, event: SellPane.SellConfirmed) -> None:
        try:
            result = self._service.execute_sell(
                market_id=event.market_id,
                side=event.side,
                shares=event.shares,
            )
        except Exception as e:
            self.notify(f"卖出失败: {e}", severity="error")
            return
        pnl = result["realized_pnl"]
        sign = "+" if pnl >= 0 else ""
        self.notify(
            f"卖出成功: {event.side.upper()} {event.shares:.2f}股 "
            f"@ {result['price'] * 100:.1f}¢  已实现 {sign}${pnl:.2f}",
        )
        self.dismiss({"action": "sell", **result, "side": event.side, "shares": event.shares})

    def action_dismiss_cancel(self) -> None:
        self.dismiss(None)

    # ----- internals -----

    def _selected_market(self):
        try:
            radio_set = self.query_one("#market-radios", RadioSet)
            idx = radio_set.pressed_index
            if 0 <= idx < len(self._markets):
                return self._markets[idx]
        except Exception:
            return self._markets[0] if self._markets else None
        return self._markets[0] if self._markets else None

    def _refresh_balance(self) -> None:
        try:
            cash = self._service.wallet.get_cash()
            self.query_one("#balance-label", Static).update(
                f"{ICON_WALLET} 余额 ${cash:.2f}",
            )
        except Exception:
            pass

    def _push_context_to_panes(self) -> None:
        market = self._selected_market()
        if market is None:
            return
        positions_here = [
            p for p in self._service.positions.get_event_positions(self.event_id)
            if p["market_id"] == market.market_id
        ]
        cash = 0.0
        with contextlib.suppress(Exception):
            cash = self._service.wallet.get_cash()
        # Fee context (fees_enabled + fee_rate) lives on the market object itself;
        # panes pull from self._market at preview time.
        self._buy_pane.update_context(
            market=market, cash=cash, positions_here=positions_here,
        )
        self._sell_pane.update_context(
            market=market, positions_here=positions_here,
        )

    def _refresh_prices_periodic(self) -> None:
        """Re-read prices from DB and update radio labels + pane context.

        Invoked by both the 3s timer (timer fallback) and TOPIC_PRICE_UPDATED
        (bus-driven refresh). Idempotent.
        """
        try:
            fresh = get_event_markets(self.event_id, self._service.db)
        except Exception:
            return
        fresh_by_id = {m.market_id: m for m in fresh}
        for m in self._markets:
            updated = fresh_by_id.get(m.market_id)
            if updated and updated.yes_price is not None:
                m.yes_price = updated.yes_price
                m.no_price = updated.no_price
        self._refresh_balance()
        self._push_context_to_panes()
