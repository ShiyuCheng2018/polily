"""Modals for monitoring lifecycle actions.

v0.8.0 migration:
- ConfirmUnmonitorModal wraps the destructive-confirm flow in PolilyZone
  (ICON_CANCELLED) with a red border override — stopping monitoring is a
  user-workflow destructive action (event drops out of the poll rotation).
- Widget IDs preserved (#dialog-box, #confirm, #keep, #btn-row) — dismiss
  protocol (True on confirm, False on keep/Escape) untouched so existing
  tests + callers in market_detail.py / monitor_list.py keep working.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from scanner.tui.icons import ICON_CANCELLED
from scanner.tui.widgets.polily_zone import PolilyZone

_MODAL_WIDTH = 62
_TITLE_TRIM = 40


class ConfirmUnmonitorModal(ModalScreen[bool]):
    """Confirm-before-disable monitor. Dismisses True on confirm, False on
    keep / Esc. No destructive action happens inside the modal — the caller
    does the actual toggle once True is received.
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
    ConfirmUnmonitorModal #btn-row {{
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }}
    ConfirmUnmonitorModal .action-btn {{ min-width: 16; margin: 0 1; }}
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
                with Horizontal(id="btn-row"):
                    yield Button(
                        "确认取消",
                        id="confirm",
                        variant="error",
                        classes="action-btn",
                    )
                    yield Button(
                        "继续监控",
                        id="keep",
                        variant="primary",
                        classes="action-btn",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm":
            self.dismiss(True)
        elif event.button.id == "keep":
            self.dismiss(False)

    def action_keep(self) -> None:
        self.dismiss(False)
