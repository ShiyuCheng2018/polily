# polily/tui/widgets/status_badge.py
"""v0.8.0 atom: StatusBadge — icon + Chinese label for scan_log statuses.

Color-coded: completed=success, failed/cancelled=error, running/pending=warning,
superseded=muted.
"""
from textual.widgets import Static

from polily.tui.i18n import translate_status
from polily.tui.icons import STATUS_ICONS

_STATUS_COLOR_CLASS = {
    "pending": "text-warning",
    "running": "text-warning",
    "completed": "text-success",
    "failed": "text-error",
    "cancelled": "text-error",
    "superseded": "text-muted",
}


class StatusBadge(Static):
    """Inline icon + Chinese status label."""

    def __init__(self, *, status: str, **kwargs) -> None:
        icon = STATUS_ICONS.get(status, "?")
        label = translate_status(status)
        super().__init__(f"{icon} {label}", **kwargs)
        self.add_class("status-badge")
        color_cls = _STATUS_COLOR_CLASS.get(status, "text-muted")
        self.add_class(color_cls)
