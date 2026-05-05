"""Helpers to keep DataTable column widths consistent through language switches.

Textual's `DataTable.add_column(label, ...)` (`textual/widgets/_data_table.py:1611`
in 8.2.4) computes `column.content_width` once from the initial label. Setting
`column.label = new_text` later does NOT recompute width, and `_update_dimensions`
only grows `content_width` from cell content (not from the label). Result: when
we switch language and the new label is wider than the old one (e.g.,
"触发"=4 cells → "Trigger"=7 cells), the header gets clipped to a stale width
(see PR-4 testing screenshots).

`set_column_label` updates label + bumps content_width to fit, then schedules
a dimension recomputation.

Coupling: depends on private attrs `column.content_width` and
`table._require_update_dimensions`. Mirrors what Textual itself does at
`_data_table.py:1402-1404`. If Textual ever exposes a public
`column.set_label()` that resizes correctly, switch to that.
"""
from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import DataTable


def set_column_label(table: DataTable, col_key: str, new_label: str) -> None:
    """Update one DataTable column's label and resize it to fit the new text.

    Args:
        table: the DataTable whose column to relabel.
        col_key: the column's stable internal key (the `key=` arg to
            add_column). No-op if the key is not in `table.columns`.
        new_label: the new label text (Rich markup OK).
    """
    if col_key not in table.columns:
        return
    column = table.columns[col_key]  # pyright: ignore[reportArgumentType]
    column.label = Text.from_markup(new_label)
    label_width = cell_len(Text.from_markup(new_label).plain)
    # Grow only — don't shrink below cell-driven width that may have
    # accumulated from row content.
    column.content_width = max(column.content_width, label_width)
    table._require_update_dimensions = True
    table.refresh()


def set_column_labels(table: DataTable, mapping: list[tuple[str, str]]) -> None:
    """Apply set_column_label to many columns at once.

    `mapping` is a list of (col_key, new_label) tuples — same shape as the
    `_COLUMN_SPEC` lists views already pass around.
    """
    for col_key, new_label in mapping:
        set_column_label(table, col_key, new_label)
