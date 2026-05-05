"""v0.8.0 atom: EmptyState — centered icon + message for empty lists."""
from textual.widgets import Static

from polily.tui.i18n import t


class EmptyState(Static):
    DEFAULT_CSS = """
    EmptyState {
        content-align: center middle;
        height: 1fr;
        color: $text-muted;
    }
    """

    def __init__(self, *, icon: str = "", message: str | None = None, **kwargs) -> None:
        # None sentinel → resolve via t() so the default flips on language
        # switch even if the widget isn't remounted.
        msg = message if message is not None else t("widget.empty.default")
        super().__init__(f"{icon}  {msg}", **kwargs)
        self.add_class("empty-state")
