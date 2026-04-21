"""v0.8.0 atom: FieldRow — label | unit | input | helper horizontal row.

Standard input-row pattern. Caller provides the Input widget (so they keep
full control over id, type, validation, etc.); FieldRow wraps it with a
right-aligned label + optional unit char + optional helper text column.

Layout:
    [label (right, fixed width)] [unit] [input (auto-flex)] [helper]

Use alongside KVRow for readonly key:value display; use FieldRow for
editable inputs.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Input, Label, Static


class FieldRow(Horizontal):
    """Label + unit + input + helper, single-row layout."""

    DEFAULT_CSS = """
    FieldRow {
        height: auto;
        padding: 0 0 1 0;
    }
    FieldRow .field-row-label {
        width: 10;
        text-align: right;
        padding: 1 1 0 0;
        color: $text-muted;
    }
    FieldRow .field-row-unit {
        width: 2;
        padding: 1 0 0 0;
        color: $accent;
    }
    FieldRow .field-row-input-wrap {
        width: 16;
    }
    FieldRow .field-row-helper {
        width: 1fr;
        padding: 1 0 0 1;
        color: $text-muted;
    }
    """

    def __init__(
        self,
        *,
        label: str,
        input_widget: Input,
        unit: str = "",
        helper: str = "",
        helper_id: str | None = None,
        id: str | None = None,  # noqa: A002 — Textual widget API convention
    ) -> None:
        super().__init__(id=id)
        self._label = label
        self._unit = unit
        self._input = input_widget
        self._helper = helper
        self._helper_id = helper_id
        # Tag the caller's Input so our CSS can size it without requiring
        # the caller to hand-add the class.
        self._input.add_class("field-row-input-wrap")

    def compose(self) -> ComposeResult:
        yield Label(self._label, classes="field-row-label")
        if self._unit:
            yield Static(self._unit, classes="field-row-unit")
        yield self._input
        helper_kwargs: dict = {"classes": "field-row-helper"}
        if self._helper_id:
            helper_kwargs["id"] = self._helper_id
        yield Static(self._helper, **helper_kwargs)

    def set_helper(self, text: str) -> None:
        """Update helper text (allows caller to show live preview/calc)."""
        helper = self.query_one(".field-row-helper", Static)
        helper.update(text)
