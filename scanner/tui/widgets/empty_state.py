"""v0.8.0 atom: EmptyState — centered icon + message for empty lists."""
from textual.widgets import Static


class EmptyState(Static):
    DEFAULT_CSS = """
    EmptyState {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, *, icon: str = "\uf119", message: str = "暂无记录", **kwargs) -> None:
        super().__init__(f"{icon}  {message}", **kwargs)
        self.add_class("empty-state")
