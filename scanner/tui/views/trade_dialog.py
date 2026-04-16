"""TradeDialog: modal popup for creating paper trades.

Flow: select sub-market (radio) → enter amount → click YES/NO button.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static


class TradeDialog(ModalScreen[str | None]):
    """Modal dialog for paper trade entry."""

    DEFAULT_CSS = """
    TradeDialog {
        align: center middle;
    }
    TradeDialog #dialog-box {
        width: 80;
        height: auto;
        max-height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 2 3;
    }
    TradeDialog #dialog-title {
        text-style: bold;
        padding: 0 0 1 0;
    }
    TradeDialog #market-radios {
        height: auto;
        max-height: 12;
        padding: 0 0 1 0;
    }
    TradeDialog #amount-row {
        height: auto;
        margin: 2 0;
    }
    TradeDialog #amount-input {
        width: 20;
    }
    TradeDialog #btn-row {
        height: auto;
        align: center middle;
        margin: 1 0;
    }
    TradeDialog .trade-btn {
        min-width: 20;
        margin: 0 1;
    }
    TradeDialog #btn-cancel {
        min-width: 10;
    }
    """

    BINDINGS = [("escape", "dismiss", "取消")]

    def __init__(self, event_id: str, markets: list, service) -> None:
        super().__init__()
        self.event_id = event_id
        self._markets = [m for m in markets if not m.closed and m.yes_price is not None]
        self._service = service

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            yield Static("建仓", id="dialog-title")

            # Sub-market radio selection
            with RadioSet(id="market-radios"):
                for i, m in enumerate(self._markets):
                    label = m.group_item_title or m.question[:30]
                    yes = f"{m.yes_price * 100:.1f}¢" if m.yes_price else "?"
                    no = f"{(m.no_price or round(1 - (m.yes_price or 0), 4)) * 100:.1f}¢"
                    yield RadioButton(f"{label}  Y:{yes} N:{no}", value=i == 0)

            # Amount input
            with Horizontal(id="amount-row"):
                yield Label("金额 $")
                yield Input(value="10", id="amount-input", type="number")

            # YES / NO / Cancel buttons — labels set in on_mount
            with Horizontal(id="btn-row"):
                yield Button("YES", id="btn-yes", variant="success", classes="trade-btn")
                yield Button("NO", id="btn-no", variant="error", classes="trade-btn")
                yield Button("取消", id="btn-cancel", variant="default")

    def on_mount(self) -> None:
        self._update_buttons()
        self._refresh_timer = self.set_interval(3, self._refresh_prices)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        self._update_buttons()

    def _refresh_prices(self) -> None:
        """Re-read prices from DB and update buttons + radio labels."""
        from scanner.core.event_store import get_event_markets
        fresh = get_event_markets(self.event_id, self._service.db)
        fresh_by_id = {m.market_id: m for m in fresh}

        for i, m in enumerate(self._markets):
            updated = fresh_by_id.get(m.market_id)
            if updated and updated.yes_price is not None:
                m.yes_price = updated.yes_price
                m.no_price = updated.no_price
                # Update radio label
                try:
                    radio_set = self.query_one("#market-radios", RadioSet)
                    buttons = list(radio_set.query(RadioButton))
                    btn = buttons[i] if i < len(buttons) else None
                    if btn is None:
                        continue
                    label = m.group_item_title or m.question[:30]
                    no = (m.no_price or round(1 - m.yes_price, 4)) * 100
                    btn.label = f"{label}  Y:{m.yes_price * 100:.1f}¢ N:{no:.1f}¢"
                except Exception:
                    pass

        self._update_buttons()

    def _get_selected_market(self):
        try:
            radio_set = self.query_one("#market-radios", RadioSet)
            idx = radio_set.pressed_index
            if 0 <= idx < len(self._markets):
                return self._markets[idx]
        except Exception:
            pass
        return self._markets[0] if self._markets else None

    @staticmethod
    def _fetch_live_entry_price(token_id: str, side: str) -> float | None:
        """Fetch real-time execution price from CLOB /price API.

        For YES buy: /price?side=SELL (the ask — what you pay).
        For NO buy: 1 - /price?side=BUY (the bid).
        Returns entry price or None on failure.
        """
        if not token_id:
            return None
        try:
            import httpx
            if side == "yes":
                # Buying YES = paying the ask
                resp = httpx.get(
                    "https://clob.polymarket.com/price",
                    params={"token_id": token_id, "side": "SELL"},
                    timeout=2,
                )
            else:
                # Buying NO = 1 - bid
                resp = httpx.get(
                    "https://clob.polymarket.com/price",
                    params={"token_id": token_id, "side": "BUY"},
                    timeout=2,
                )
            if resp.status_code == 200:
                price = float(resp.json().get("price", 0))
                return price if side == "yes" else round(1 - price, 4)
        except Exception:
            pass
        return None

    def _update_buttons(self) -> None:
        m = self._get_selected_market()
        if not m:
            return
        yes_price = m.yes_price or 0
        no_price = m.no_price or round(1 - yes_price, 4)
        try:
            self.query_one("#btn-yes", Button).label = f"YES {yes_price * 100:.1f}¢"
            self.query_one("#btn-no", Button).label = f"NO {no_price * 100:.1f}¢"
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(None)
            return

        if event.button.id not in ("btn-yes", "btn-no"):
            return

        m = self._get_selected_market()
        if not m:
            self.notify("请选择子市场")
            return

        # Parse amount
        try:
            amount_input = self.query_one("#amount-input", Input)
            amount = float(amount_input.value)
            if amount <= 0:
                self.notify("金额必须大于 0")
                return
        except (ValueError, TypeError):
            self.notify("请输入有效金额")
            return

        side = "yes" if event.button.id == "btn-yes" else "no"

        # Fetch real-time execution price from CLOB API
        entry_price = self._fetch_live_entry_price(m.clob_token_id_yes, side)
        if entry_price is None:
            # Fallback to DB price
            yes_price = m.yes_price or 0
            entry_price = yes_price if side == "yes" else round(1 - yes_price, 4)

        from scanner.core.paper_store import create_paper_trade

        trade_id = create_paper_trade(
            event_id=self.event_id,
            market_id=m.market_id,
            title=m.group_item_title or m.question[:40],
            side=side,
            entry_price=entry_price,
            position_size_usd=amount,
            structure_score=m.structure_score,
            db=self._service.db,
        )

        self.notify(f"建仓成功: {side.upper()} @ {entry_price * 100:.1f}¢ ${amount:.0f}")
        self.dismiss(trade_id)
