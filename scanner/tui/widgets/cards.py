"""Reusable card widgets for dashboard layout."""

from textual.containers import Vertical
from textual.widgets import Static


class MetricCard(Static):
    """Small bordered card for KPI row."""

    DEFAULT_CSS = """
    MetricCard {
        width: 1fr;
        height: 5;
        border: round $accent;
        padding: 0 1;
        content-align: center middle;
        text-align: center;
    }
    """


class DashPanel(Vertical):
    """Bordered panel with title for dashboard sections."""

    DEFAULT_CSS = """
    DashPanel {
        border: round $primary;
        width: 1fr;
        height: auto;
        padding: 0 1;
        overflow-y: auto;
    }
    """
