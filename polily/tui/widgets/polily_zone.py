# polily/tui/widgets/polily_zone.py
"""v0.8.0 atom: PolilyZone — standard bordered container with title header.

Used as the canonical "section" unit across all views. Enforces consistent
padding ($space-md internal) and border styling via theme tokens.

Composition:
    ┌─ 测试标题 ──────────────────┐
    │                              │
    │  <child content>             │
    │                              │
    └──────────────────────────────┘

Title is mounted as the FIRST child in `on_mount()` via
`self.mount(..., before=0)` so that when used as a context manager
(`with PolilyZone(title=...):`), the title stays at the top regardless of
how many children the parent compose yielded inside the `with` block.
Previous implementation yielded the title from `compose()`, which Textual
appended AFTER context-manager children, causing the title to appear at
the BOTTOM of the zone — see v0.8.0 bug fix.
"""
from textual.containers import Vertical
from textual.widgets import Static


class PolilyZone(Vertical):
    """Bordered zone with title. Standard v0.8.0 section container."""

    DEFAULT_CSS = """
    PolilyZone {
        border: round $primary;
        padding: 1 3;
        margin: 1 0;
        background: $surface;
        height: auto;
    }
    PolilyZone .polily-zone-title {
        text-style: bold;
        color: $primary;
        padding: 0 0 1 0;
    }
    """

    def __init__(self, *, title: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self.add_class("polily-zone")

    def on_mount(self) -> None:
        if self._title:
            self.mount(
                Static(self._title, classes="polily-zone-title"),
                before=0,
            )
