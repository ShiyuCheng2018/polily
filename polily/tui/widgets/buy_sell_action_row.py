"""v0.8.0 atom: BuySellActionRow — 买 YES / 买 NO (or 卖) action button pair.

Emits BuySellActionRow.Pressed(outcome) when clicked. Caller subscribes via
@on(BuySellActionRow.Pressed) and dispatches to execute_buy/execute_sell.

The atom owns:
- Green/red variant styling (success for YES, error for NO)
- Label formatting "{side_verb} {outcome} {price}¢"
- Disabled state per outcome (e.g. sell disabled if no position on that side)

Caller owns:
- When to call update(yes_price=..., no_price=..., yes_disabled=..., no_disabled=...)
- What execute logic runs on Pressed
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button


class BuySellActionRow(Horizontal):
    """Pair of YES/NO action buttons for buy or sell context."""

    class Pressed(Message):
        """YES or NO action button pressed."""
        def __init__(self, outcome: str, side: str) -> None:
            super().__init__()
            self.outcome = outcome  # "yes" or "no"
            self.side = side         # "buy" or "sell"

    DEFAULT_CSS = """
    BuySellActionRow {
        height: auto;
        align: center middle;
        padding: 1 0;
    }
    BuySellActionRow Button {
        min-width: 20;
        margin: 0 1;
    }
    """

    def __init__(self, *, side: str = "buy") -> None:
        """side: 'buy' or 'sell' — determines the verb in button labels."""
        super().__init__()
        if side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
        self._side = side
        self._yes_price: float | None = None
        self._no_price: float | None = None
        self._yes_disabled = False
        self._no_disabled = False

    def compose(self) -> ComposeResult:
        verb = "买" if self._side == "buy" else "卖"
        yield Button(
            f"{verb} YES", id="btn-yes", variant="success", classes="trade-btn",
        )
        yield Button(
            f"{verb} NO", id="btn-no", variant="error", classes="trade-btn",
        )

    # Sentinel distinguishes "not passed" from "explicitly None (unavailable)".
    _UNSET: object = object()

    def update(
        self,
        *,
        yes_price: float | None = _UNSET,  # type: ignore[assignment]
        no_price: float | None = _UNSET,   # type: ignore[assignment]
        yes_disabled: bool | None = None,
        no_disabled: bool | None = None,
    ) -> None:
        """Update button labels + disabled state.

        Omitted kwargs retain their previously-set value. Pass ``None`` for
        ``yes_price``/``no_price`` to explicitly mark a price as unavailable
        (button label becomes "YES (价格不可用)" and the button is disabled).
        """
        if yes_price is not self._UNSET:
            self._yes_price = yes_price  # type: ignore[assignment]
        if no_price is not self._UNSET:
            self._no_price = no_price  # type: ignore[assignment]
        if yes_disabled is not None:
            self._yes_disabled = yes_disabled
        if no_disabled is not None:
            self._no_disabled = no_disabled
        self._refresh()

    def _refresh(self) -> None:
        verb = "买" if self._side == "buy" else "卖"
        yes_btn = self.query_one("#btn-yes", Button)
        no_btn = self.query_one("#btn-no", Button)
        if self._yes_price is not None and 0 < self._yes_price < 1:
            yes_btn.label = f"{verb} YES {self._yes_price * 100:.1f}¢"
        else:
            yes_btn.label = "YES (价格不可用)"
        if self._no_price is not None and 0 < self._no_price < 1:
            no_btn.label = f"{verb} NO {self._no_price * 100:.1f}¢"
        else:
            no_btn.label = "NO (价格不可用)"
        # Disabled: caller-specified OR price-missing (which makes button useless)
        yes_btn.disabled = self._yes_disabled or (self._yes_price is None)
        no_btn.disabled = self._no_disabled or (self._no_price is None)

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-yes":
            self.post_message(self.Pressed(outcome="yes", side=self._side))
            event.stop()
        elif event.button.id == "btn-no":
            self.post_message(self.Pressed(outcome="no", side=self._side))
            event.stop()
