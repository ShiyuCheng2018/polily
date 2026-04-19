"""ArchivedEventsView: list of events the user was monitoring when they closed.

Data source: `events` + `event_monitors` join (no dedicated archive table).
Rows clickable → navigate to MarketDetailView for retrospective view.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.service import ScanService


class ViewArchivedDetail(Message):
    """Row-click → navigate to the event's detail page."""

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


_COLUMN_SPEC = [
    ("事件", "title"),
    ("结构分", "score"),
    ("子市场", "count"),
    ("关闭于", "closed_at"),
]


class ArchivedEventsView(Widget):
    BINDINGS = [Binding("enter", "view_detail", "详情")]

    DEFAULT_CSS = """
    ArchivedEventsView { height: 1fr; }
    ArchivedEventsView #archive-title { padding: 1 0 0 0; text-style: bold; }
    ArchivedEventsView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._events: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="archive-title")
        yield DataTable(id="archive-table")
        yield Static("", id="archive-empty", classes="empty-msg")

    def on_mount(self) -> None:
        self._events = self.service.get_archived_events()
        self.query_one("#archive-title", Static).update(
            f" 归档事件 ({len(self._events)})",
        )
        table = self.query_one("#archive-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(*_COLUMN_SPEC)

        empty_msg = self.query_one("#archive-empty", Static)
        if not self._events:
            empty_msg.update(" 暂无归档事件。")
            return
        empty_msg.display = False

        for e in self._events:
            ev = e["event"]
            mc = e["market_count"]
            score_str = f"{ev.structure_score:.0f}" if ev.structure_score else "—"
            count_str = f"{mc} 个" if mc > 1 else "二元"
            closed_at = (ev.updated_at or "")[:10]  # YYYY-MM-DD
            table.add_row(
                ev.title[:45], score_str, count_str, closed_at,
                key=ev.event_id,
            )

    def _selected_event_id(self) -> str | None:
        if not self._events:
            return None
        try:
            table = self.query_one("#archive-table", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row < 0 or row >= len(self._events):
            return None
        return self._events[row]["event"].event_id

    def action_view_detail(self) -> None:
        eid = self._selected_event_id()
        if eid:
            self.post_message(ViewArchivedDetail(eid))

    def on_data_table_row_selected(self, _event: DataTable.RowSelected) -> None:
        eid = self._selected_event_id()
        if eid:
            self.post_message(ViewArchivedDetail(eid))
