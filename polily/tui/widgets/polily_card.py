# polily/tui/widgets/polily_card.py
"""v0.8.0 atom: PolilyCard — compact container for metrics / summaries.

Differs from PolilyZone in:
- Tighter padding (space-sm, not space-md)
- Different background (panel, not surface)
- Intended for grouping small info blocks (e.g. wallet balance trio)

Title is mounted as the FIRST child in `on_mount()` via
`self.mount(..., before=0)` so that when used as a context manager
(`with PolilyCard(title=...):`), the title stays at the top regardless of
how many children the parent compose yielded inside the `with` block.
Previous implementation yielded the title from `compose()`, which Textual
appended AFTER context-manager children, causing the title to appear at
the BOTTOM of the card — see PolilyZone aa9bc27 for the matching fix.

`height: auto` is explicit so that when nested in layouts with
`align: center middle` + auto-sizing parents (e.g. modal dialogs), the
card doesn't stretch to fill its parent's height.
"""
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
        height: auto;
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

    def on_mount(self) -> None:
        if self._title:
            self.mount(
                Static(self._title, classes="polily-card-title"),
                before=0,
            )
