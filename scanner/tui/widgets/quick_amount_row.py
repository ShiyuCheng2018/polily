"""v0.8.0 atom: QuickAmountRow — row of numeric-amount buttons.

Emits QuickAmountRow.Selected(amount) when any button clicked. Caller uses
@on(QuickAmountRow.Selected) to respond (typically fills an Input with the
amount). The atom itself does NOT touch Inputs — it only emits the event,
keeping it decoupled from DOM structure.

For special tokens like "全部"/"all" (meaning max available), the atom
supports str amounts alongside numeric ones. Caller decides how to resolve
non-numeric tokens.

Button id format:
  - Numeric amount: ``quick-<N>``         e.g. ``quick-50``
  - String token:   ``quick-<token>``     e.g. ``quick-全部``
    Textual widget ids only accept ASCII letters/digits/underscores/hyphens,
    so non-ASCII tokens are indexed by position (``quick-tok-0``,
    ``quick-tok-1``…) internally. Callers still receive the original token
    via the ``Selected`` message — do not rely on the id structure for
    non-ASCII values.
"""
from __future__ import annotations

import re

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button

# Textual widget-id rules: ASCII letter/digit/underscore/hyphen, can't start
# with a digit. We allow digits mid-id because our prefix ``quick-`` makes
# the overall id safe. Non-ASCII tokens (e.g. "全部") get a positional id.
_ASCII_ID_TAIL = re.compile(r"^[A-Za-z0-9_\-]+$")


class QuickAmountRow(Horizontal):
    """Row of amount-quick-pick buttons."""

    class Selected(Message):
        """Quick amount button pressed."""
        def __init__(self, amount: int | str) -> None:
            super().__init__()
            self.amount = amount  # int for numeric; str for "全部" / "all" etc.

    DEFAULT_CSS = """
    QuickAmountRow {
        height: auto;
        padding: 0 0 1 0;
    }
    QuickAmountRow Button {
        min-width: 6;
        margin: 0 1 0 0;
    }
    """

    def __init__(
        self,
        *,
        amounts: list[int | str],
        unit: str = "$",
    ) -> None:
        super().__init__()
        self._amounts = amounts
        self._unit = unit
        # Map: button-id -> original amount (so we can round-trip non-ASCII
        # tokens that can't live in Textual ids literally).
        self._id_to_amount: dict[str, int | str] = {}

    def _button_id_for(self, idx: int, amount: int | str) -> str:
        """Compute a Textual-safe id for the given amount.

        Numeric and ASCII-safe string tokens get the literal id
        ``quick-<amount>``. Non-ASCII tokens fall back to a positional id
        ``quick-tok-<idx>``.
        """
        if isinstance(amount, int):
            return f"quick-{amount}"
        if _ASCII_ID_TAIL.match(amount):
            return f"quick-{amount}"
        return f"quick-tok-{idx}"

    def compose(self) -> ComposeResult:
        for idx, amt in enumerate(self._amounts):
            if isinstance(amt, int):
                label = f"{self._unit}{amt}"
            else:
                label = str(amt)  # e.g. "全部" passes through as-is
            btn_id = self._button_id_for(idx, amt)
            self._id_to_amount[btn_id] = amt
            yield Button(label, id=btn_id, classes="quick-btn")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if not btn_id or btn_id not in self._id_to_amount:
            return  # foreign button — let it bubble
        self.post_message(self.Selected(self._id_to_amount[btn_id]))
        event.stop()
