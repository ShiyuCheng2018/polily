# scanner/tui/widgets/kv_row.py
"""v0.8.0 atom: KVRow — label:value row with consistent spacing and alignment.

Standard pattern for key-value display in detail views (wallet, market_detail).
Label right-aligned with fixed width so multiple KVRows visually align.
"""
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class KVRow(Horizontal):
    """Label : Value row with aligned columns."""

    DEFAULT_CSS = """
    KVRow {
        height: 1;
        padding: 0 0;
    }
    KVRow .kv-label {
        width: 14;
        color: $text-muted;
        text-align: right;
        padding: 0 1 0 0;
    }
    KVRow .kv-value {
        width: 1fr;
        color: $text;
    }
    """

    def __init__(self, *, label: str, value: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._label = label
        self._value = value

    def compose(self) -> ComposeResult:
        yield Static(self._label, classes="kv-label")
        yield Static(self._value, classes="kv-value")
