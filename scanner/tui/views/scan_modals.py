"""Modals for scan log actions — currently: confirm-cancel-running."""
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmCancelScanModal(ModalScreen[bool]):
    """Ask before killing a running analysis.

    Dismisses with True on '确认取消', False on '继续分析' or Escape.
    """

    DEFAULT_CSS = """
    ConfirmCancelScanModal > Vertical {
        background: $panel;
        border: round $primary;
        padding: 2 4;
        width: 60;
        height: auto;
    }
    ConfirmCancelScanModal .row { padding: 1 0; }
    ConfirmCancelScanModal #btn-row {
        height: auto;
        align: center middle;
        padding-top: 1;
    }
    ConfirmCancelScanModal Button { margin: 0 1; }
    """

    BINDINGS = [("escape", "dismiss_false", "取消")]

    def __init__(self, event_title: str, elapsed_seconds: float):
        super().__init__()
        self._title = event_title
        self._elapsed = elapsed_seconds

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[bold]确认取消 AI 分析？[/bold]", classes="row")
            yield Static(f"事件: {self._title} · 正在分析... ({self._elapsed:.0f}s)", classes="row")
            yield Static(
                "[dim]取消后此次分析不会完成，scan_log 记录为 cancelled。[/dim]",
                classes="row",
            )
            with Horizontal(id="btn-row"):
                yield Button("确认取消", id="confirm", variant="error")
                yield Button("继续分析", id="keep", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)
