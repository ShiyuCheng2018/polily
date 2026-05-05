"""v0.8.0 atom: LoadingState — spinner + message.

Static non-animated spinner character — avoids timer churn on idle views.
If true animation needed, caller uses Textual's LoadingIndicator directly.
"""
from textual.widgets import Static

from polily.tui.i18n import t


class LoadingState(Static):
    DEFAULT_CSS = """
    LoadingState {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, *, message: str | None = None, **kwargs) -> None:
        msg = message if message is not None else t("widget.loading.default")
        super().__init__(f"  {msg}...", **kwargs)  # refresh icon
        self.add_class("loading-state")
