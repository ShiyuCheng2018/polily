"""v0.8.0 atom: SectionHeader — h2-styled row with optional leading icon."""
from textual.widgets import Static


class SectionHeader(Static):
    DEFAULT_CSS = """
    SectionHeader {
        text-style: bold;
        color: $text;
        padding: 1 0 0 0;
        border-bottom: heavy $primary;
    }
    """

    def __init__(self, *, title: str, icon: str = "", **kwargs) -> None:
        content = f"{icon}  {title}" if icon else title
        super().__init__(content, **kwargs)
        self.add_class("section-header")
