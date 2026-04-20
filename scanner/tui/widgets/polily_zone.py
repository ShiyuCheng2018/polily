# scanner/tui/widgets/polily_zone.py
"""v0.8.0 atom: PolilyZone — standard bordered container with title header.

Used as the canonical "section" unit across all views. Enforces consistent
padding ($space-md internal) and border styling via theme tokens.

Composition:
    ┌─ 测试标题 ──────────────────┐
    │                              │
    │  <child content>             │
    │                              │
    └──────────────────────────────┘
"""
from textual.app import ComposeResult
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

    def compose(self) -> ComposeResult:
        if self._title:
            yield Static(self._title, classes="polily-zone-title")
