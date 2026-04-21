"""ConfirmCancelBar — v0.8.0 atom replacing the hand-written Horizontal + 2
Button row for 确认/取消 flows across modals.

Emits Confirmed / Cancelled messages that bubble up to the parent
ModalScreen, which decides what to dismiss with. The destructive=True
variant flips the confirm button to the 'error' variant for destructive
flows (reset wallet, cancel analysis, stop monitoring).

Button ids are stable: `#confirm` and `#cancel`. Existing modals that
previously used `#ok` / `#keep` have been migrated to the new ids as part
of the same change.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button


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
        confirm_label: str = "确认",
        cancel_label: str = "取消",
        destructive: bool = False,
    ) -> None:
        super().__init__()
        self._confirm_label = confirm_label
        self._cancel_label = cancel_label
        self._destructive = destructive

    def compose(self) -> ComposeResult:
        confirm_variant = "error" if self._destructive else "primary"
        yield Button(self._confirm_label, id="confirm", variant=confirm_variant)
        yield Button(self._cancel_label, id="cancel", variant="default")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.post_message(self.Confirmed())
            event.stop()
        elif event.button.id == "cancel":
            self.post_message(self.Cancelled())
            event.stop()
