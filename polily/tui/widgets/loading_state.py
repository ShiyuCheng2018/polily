"""v0.8.0 atom: LoadingState — spinner + message.

Static non-animated spinner character — avoids timer churn on idle views.
If true animation needed, caller uses Textual's LoadingIndicator directly.
"""
from textual.widgets import Static


class LoadingState(Static):
    DEFAULT_CSS = """
    LoadingState {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, *, message: str = "加载中", **kwargs) -> None:
        super().__init__(f"\uf021  {message}...", **kwargs)  # refresh icon
        self.add_class("loading-state")
