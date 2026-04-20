"""Modals for scan log actions — currently: confirm-cancel-running.

v0.8.0 migration:
- ConfirmCancelScanModal wraps the destructive-confirm flow in PolilyZone
  (ICON_CANCELLED) with a red border override — cancelling a running
  analysis is destructive (scan_log becomes `cancelled`).
- Widget IDs preserved (#confirm, #keep, #btn-row) — dismiss protocol
  (True on confirm, False on keep/Escape) untouched.
"""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from scanner.tui.icons import ICON_CANCELLED
from scanner.tui.widgets.polily_zone import PolilyZone


class ConfirmCancelScanModal(ModalScreen[bool]):
    """Ask before killing a running analysis.

    Dismisses with True on '确认取消', False on '继续分析' or Escape.
    """

    DEFAULT_CSS = """
    ConfirmCancelScanModal {
        align: center middle;
    }
    ConfirmCancelScanModal #dialog-box {
        width: 62;
        height: auto;
    }
    ConfirmCancelScanModal > #dialog-box > PolilyZone {
        height: auto;
        margin: 0;
        border: round $error;
    }
    ConfirmCancelScanModal .polily-zone-title { color: $error; }
    ConfirmCancelScanModal .row { padding: 0 0 1 0; }
    ConfirmCancelScanModal #btn-row {
        height: auto;
        align: center middle;
        padding: 1 0 0 0;
    }
    ConfirmCancelScanModal .action-btn { min-width: 14; margin: 0 1; }
    """

    BINDINGS = [("escape", "dismiss_false", "取消")]

    def __init__(self, event_title: str, elapsed_seconds: float):
        super().__init__()
        self._title = event_title
        self._elapsed = elapsed_seconds

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog-box"):
            with PolilyZone(title=f"{ICON_CANCELLED} 取消分析"):
                yield Static(
                    f"[b]事件:[/b] {self._title}",
                    classes="row",
                )
                yield Static(
                    f"[dim]正在运行的分析已耗时 {self._elapsed:.0f}s[/dim]",
                    classes="row",
                )
                yield Static(
                    "[b red]⚠  取消后此次分析无法恢复[/b red]\n"
                    "[dim]    分析记录将标记为已取消。[/dim]",
                    classes="row",
                )
                with Horizontal(id="btn-row"):
                    yield Button(
                        "确认取消",
                        id="confirm",
                        variant="error",
                        classes="action-btn",
                    )
                    yield Button(
                        "继续分析",
                        id="keep",
                        variant="primary",
                        classes="action-btn",
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)
