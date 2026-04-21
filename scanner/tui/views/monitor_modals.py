"""Modals for monitoring lifecycle actions.

v0.8.0 migration:
- ConfirmUnmonitorModal wraps the destructive-confirm flow in PolilyZone
  (ICON_CANCELLED) with a red border override — stopping monitoring is a
  user-workflow destructive action (event drops out of the poll rotation).
- Button row replaced with ConfirmCancelBar atom (Opt-A1). Button ids are
  now `#confirm` + `#cancel` (previously `#confirm` + `#keep`).
- dismiss protocol (True on confirm, False on cancel/Escape) untouched so
  existing callers in market_detail.py / monitor_list.py keep working.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

from scanner.tui.icons import ICON_CANCELLED
from scanner.tui.widgets.confirm_cancel_bar import ConfirmCancelBar
from scanner.tui.widgets.polily_zone import PolilyZone

_MODAL_WIDTH = 62
_TITLE_TRIM = 40


class ConfirmUnmonitorModal(ModalScreen[bool]):
    """Confirm-before-disable monitor. Dismisses True on confirm, False on
    cancel / Esc. No destructive action happens inside the modal — the
    caller does the actual toggle once True is received.
    """

    DEFAULT_CSS = f"""
    ConfirmUnmonitorModal {{
        align: center middle;
    }}
    ConfirmUnmonitorModal #dialog-box {{
        width: {_MODAL_WIDTH};
        height: auto;
    }}
    ConfirmUnmonitorModal > #dialog-box > PolilyZone {{
        height: auto;
        margin: 0;
        border: round $error;
    }}
    ConfirmUnmonitorModal .polily-zone-title {{ color: $error; }}
    ConfirmUnmonitorModal .event-line {{ color: $text-muted; padding: 0 0 1 0; }}
    ConfirmUnmonitorModal ConfirmCancelBar Button {{ min-width: 16; }}
    """
    BINDINGS = [("escape", "keep", "继续监控")]

    def __init__(self, event_title: str) -> None:
        super().__init__()
        self._event_title = event_title[:_TITLE_TRIM]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            with PolilyZone(title=f"{ICON_CANCELLED} 确认取消监控"):
                yield Static(self._event_title, classes="event-line")
                yield Static(
                    "[dim]取消后此事件将从监控轮询中移除。[/dim]",
                    classes="event-line",
                )
                yield ConfirmCancelBar(
                    confirm_label="确认取消",
                    cancel_label="继续监控",
                    destructive=True,
                )

    def on_confirm_cancel_bar_confirmed(
        self, event: ConfirmCancelBar.Confirmed,
    ) -> None:
        self.dismiss(True)

    def on_confirm_cancel_bar_cancelled(
        self, event: ConfirmCancelBar.Cancelled,
    ) -> None:
        self.dismiss(False)

    def action_keep(self) -> None:
        self.dismiss(False)
