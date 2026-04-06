"""NotificationListView: show notification history with read/unread status."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static


class NotificationListView(Widget):
    """Notification history view."""

    DEFAULT_CSS = """
    NotificationListView { height: 1fr; }
    NotificationListView #notif-title { padding: 1 0 0 0; text-style: bold; }
    NotificationListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, db):
        super().__init__()
        self._db = db
        from scanner.notifications import get_unread_notifications, mark_all_read
        self._notifications = get_unread_notifications(db)
        # Mark all as read on view
        if self._notifications:
            mark_all_read(db)

    def compose(self) -> ComposeResult:
        count = len(self._notifications)
        yield Static(f" 通知 ({count} 条未读)", id="notif-title")
        if not self._notifications:
            yield Static(" 没有未读通知。", classes="empty-msg")
        else:
            yield DataTable(id="notif-table")

    def on_mount(self) -> None:
        if not self._notifications:
            return
        try:
            table = self.query_one("#notif-table", DataTable)
        except Exception:
            return
        table.cursor_type = "row"
        table.add_columns("时间", "状态", "市场", "详情")
        for n in self._notifications:
            created = n["created_at"][:16] if n["created_at"] else "-"
            title = n["title"][:30] if n["title"] else "-"
            body = n["body"][:40] if n["body"] else "-"
            result = (n["action_result"] or "-").upper()
            table.add_row(created, result, title, body)
