# scanner/tui/widgets/polily_card.py
"""v0.8.0 atom: PolilyCard — compact container for metrics / summaries.

Differs from PolilyZone in:
- Tighter padding (space-sm, not space-md)
- Different background (panel, not surface)
- Intended for grouping small info blocks (e.g. wallet balance trio)
"""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class PolilyCard(Vertical):
    """Compact card container for metrics/summaries."""

    DEFAULT_CSS = """
    PolilyCard {
        border: round $secondary;
        padding: 1 2;
        margin: 0 1;
        background: $panel;
    }
    PolilyCard .polily-card-title {
        text-style: bold;
        color: $secondary;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, *, title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self.add_class("polily-card")

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, classes="polily-card-title")
