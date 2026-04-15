"""MonitorListView: shows events with active monitoring."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.service import ScanService


class ViewMonitorDetail(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class MonitorListView(Widget):
    BINDINGS = [
        Binding("enter", "view_detail", "详情"),
        Binding("m", "toggle_monitor", "关闭监控"),
    ]

    DEFAULT_CSS = """
    MonitorListView { height: 1fr; }
    MonitorListView #monitor-title { padding: 1 0 0 0; text-style: bold; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield Static(" 自动监控", id="monitor-title")
        yield DataTable(id="monitor-table")

    def on_mount(self):
        table = self.query_one("#monitor-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            ("事件", "title"), ("子市场", "count"), ("状态", "status"), ("下次检查", "next_check"),
        )
        self._load_data(table)

    def _load_data(self, table):
        # Get all events, filter to monitored
        events = self.service.get_all_events()
        self._monitored = [e for e in events if e["is_monitored"]]

        if not self._monitored:
            return

        for e in self._monitored:
            ev = e["event"]
            mc = e["market_count"]
            nc = e.get("next_check_at")
            next_check = nc[:16] if nc else "-"

            table.add_row(
                ev.title[:45],
                f"{mc} 个" if mc > 1 else "二元",
                "监控中",
                next_check,
                key=ev.event_id,
            )

    def _get_selected(self):
        if not hasattr(self, "_monitored") or not self._monitored:
            return None
        try:
            table = self.query_one("#monitor-table", DataTable)
            row = table.cursor_row
            if row >= len(self._monitored):
                return None
            return self._monitored[row]
        except Exception:
            return None

    def on_data_table_row_selected(self, event):
        e = self._get_selected()
        if e:
            self.post_message(ViewMonitorDetail(e["event"].event_id))

    def action_view_detail(self):
        e = self._get_selected()
        if e:
            self.post_message(ViewMonitorDetail(e["event"].event_id))

    def action_toggle_monitor(self):
        e = self._get_selected()
        if not e:
            return
        eid = e["event"].event_id
        self.service.toggle_monitor(eid, enable=False)
        self.notify(f"关闭监控: {e['event'].title[:30]}")
        self.screen.refresh_sidebar_counts()
        # Remove row from table
        try:
            table = self.query_one("#monitor-table", DataTable)
            table.remove_row(eid)
            self._monitored = [m for m in self._monitored if m["event"].event_id != eid]
        except Exception:
            pass

    def refresh_data(self) -> None:
        """Incremental update: refresh monitored events data in-place."""
        try:
            table = self.query_one("#monitor-table", DataTable)
        except Exception:
            return

        events = self.service.get_all_events()
        fresh = {e["event"].event_id: e for e in events if e["is_monitored"]}

        for e in self._monitored:
            eid = e["event"].event_id
            new = fresh.get(eid)
            if not new:
                continue
            nc = new.get("next_check_at")
            next_check = nc[:16] if nc else "-"
            try:
                table.update_cell(eid, "next_check", next_check)
            except Exception:
                pass

        self._monitored = [e for e in events if e["is_monitored"]]
