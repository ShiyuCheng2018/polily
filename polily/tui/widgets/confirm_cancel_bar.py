"""ConfirmCancelBar — v0.8.0 atom replacing the hand-written Horizontal + 2
Button row for 确认/取消 flows across modals.

Emits Confirmed / Cancelled messages that bubble up to the parent
ModalScreen, which decides what to dismiss with. The destructive=True
variant flips the confirm button to the 'error' variant for destructive
flows (reset wallet, cancel analysis, stop monitoring).

Button ids are stable: `#confirm` and `#cancel`. Existing modals that
previously used `#ok` / `#keep` have been migrated to the new ids as part
of the same change.

i18n: callers can pass explicit `confirm_label` / `cancel_label` for
context-specific wording (e.g. "Reset" / "Confirm Cancel"). When omitted,
labels default to the i18n catalog's `modal.confirm` / `binding.cancel`
keys, resolved at compose time so they flip on language switch.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button

from polily.tui.i18n import t


class ConfirmCancelBar(Horizontal):
    """v0.8.0 atom: standard confirm/cancel button row for modals.

    Emits Confirmed / Cancelled messages (bubble up to parent ModalScreen,
    which decides what to dismiss with). Destructive variant uses 'error'
    variant + red styling for the confirm button.
    """

    class Confirmed(Message):
        """Confirm button pressed."""

    class Cancelled(Message):
        """Cancel button pressed."""

    DEFAULT_CSS = """
    ConfirmCancelBar {
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    ConfirmCancelBar Button {
        margin: 0 1;
        min-width: 10;
    }
    """

    def __init__(
        self,
        *,
        confirm_label: str | None = None,
        cancel_label: str | None = None,
        destructive: bool = False,
    ) -> None:
        super().__init__()
        # None sentinel → resolve via t() at compose time so the label flips
        # on language switch even on long-lived modals. Explicit strings
        # (e.g. caller passes t('reset.confirm_button') already-evaluated)
        # are honored as-is.
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label
        self._destructive = destructive

    def compose(self) -> ComposeResult:
        confirm_variant = "error" if self._destructive else "primary"
        confirm_label = self._confirm_label if self._confirm_label is not None else t("modal.confirm")
        cancel_label = self._cancel_label if self._cancel_label is not None else t("binding.cancel")
        yield Button(confirm_label, id="confirm", variant=confirm_variant)
        yield Button(cancel_label, id="cancel", variant="default")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.post_message(self.Confirmed())
            event.stop()
        elif event.button.id == "cancel":
            self.post_message(self.Cancelled())
            event.stop()
