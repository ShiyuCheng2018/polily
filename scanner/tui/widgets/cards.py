"""Reusable card widgets for dashboard layout.

v0.8.0 Task 32: preserved alongside the newer atoms (`PolilyCard`,
`PolilyZone`). Existing callers (event_kpi, analysis_panel,
binary_structure_panel) stay functional; v0.9.0 can decide whether these
overlap enough with the atoms to retire. Styling here uses theme variables
only — no hardcoded colors — so the brand theme fully controls them.
"""

from textual.containers import Vertical
from textual.widgets import Static


class MetricCard(Static):
    """Small bordered card for KPI row."""

    DEFAULT_CSS = """
    MetricCard {
        width: 1fr;
        height: auto;
        min-height: 5;
        max-height: 8;
        border: round $accent;
        background: $surface;
        padding: 0 1;
        content-align: center middle;
        text-align: center;
        color: $text;
    }
    """


class DashPanel(Vertical):
    """Bordered panel with title for dashboard sections."""

    DEFAULT_CSS = """
    DashPanel {
        border: round $primary;
        background: $surface;
        width: 1fr;
        height: auto;
        padding: 0 1;
        overflow-y: auto;
    }
    """
