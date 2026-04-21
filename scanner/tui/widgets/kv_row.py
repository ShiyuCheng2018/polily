# scanner/tui/widgets/kv_row.py
"""v0.8.0 atom: KVRow — label:value row with consistent spacing and alignment.

Standard pattern for key-value display in detail views (wallet, event_detail).
Label right-aligned with fixed width so multiple KVRows visually align.
"""
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class KVRow(Horizontal):
    """Label : Value row with aligned columns."""

    DEFAULT_CSS = """
    /* v0.8.0+: height: auto so long values wrap to multiple lines instead
       of being truncated (e.g. 原因 field with full reason text). Short
       values still render as 1 line; no visual change for those. */
    KVRow {
        height: auto;
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

    def set_value(self, value: str) -> None:
        """Update the value Static in place.

        Enables the "mount once, refresh in place" pattern — callers
        can re-render periodically without leaving stale KVRow widgets
        behind (Textual's `remove()` is deferred, so remount-style
        re-renders can briefly double-display).
        """
        self._value = value
        # Not yet mounted → `compose` will pick up the new `_value` when
        # it runs; swallow query errors until then.
        import contextlib
        with contextlib.suppress(Exception):
            self.query_one(".kv-value", Static).update(value)
