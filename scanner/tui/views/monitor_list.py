"""MonitorListView: shows events with active monitoring.

Role: answer "what am I monitoring, and when's the next poll?" plus a few
routing hints (structure score, AI analysis version, latest movement
signal). Trade / position / P&L details live on their respective pages.
"""

import contextlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.monitor_format import (
    format_ai_version,
    format_movement,
    format_next_check,
    format_settlement_range,
)
from scanner.tui.service import ScanService


class ViewMonitorDetail(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


_COLUMN_SPEC = [
    ("事件", "title"),
    ("结构分", "score"),
    ("子市场", "count"),
    ("AI版", "ai"),
    ("异动", "movement"),
    ("结算", "settlement"),
    ("下次检查", "next_check"),
]


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
        table.add_columns(*_COLUMN_SPEC)
        self._load_data(table)

    def _load_data(self, table):
        events = self.service.get_all_events()
        self._monitored = [e for e in events if e["is_monitored"]]

        if not self._monitored:
            return

        for e in self._monitored:
            ev = e["event"]
            mc = e["market_count"]
            score_str = f"{ev.structure_score:.0f}" if ev.structure_score else "—"
            count_str = f"{mc} 个" if mc > 1 else "二元"
            ai_str = format_ai_version(e.get("analysis_count", 0))

            mov = e.get("movement")
            if mov:
                movement_str = format_movement(
                    mov["label"], mov["magnitude"], mov["quality"],
                )
            else:
                movement_str = "—"

            settlement_str = format_settlement_range(
                e.get("markets_end_min"), e.get("markets_end_max"),
            )
            next_check_str = format_next_check(e.get("next_check_at"))

            table.add_row(
                ev.title[:45],
                score_str,
                count_str,
                ai_str,
                movement_str,
                settlement_str,
                next_check_str,
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
        title = e["event"].title

        # Block: event with open positions can't be unmonitored — closing it
        # would silently stop auto-resolution.
        pos_count = self.service.get_event_position_count(eid)
        if pos_count > 0:
            self.notify(
                f"无法取消监控 — 该事件有 {pos_count} 个持仓未结算，"
                "请先平仓或等待结算",
                severity="warning",
            )
            return

        from scanner.tui.views.monitor_modals import ConfirmUnmonitorModal

        def _on_dismiss(confirmed: bool | None) -> None:
            if not confirmed:
                return
            self.service.toggle_monitor(eid, enable=False)
            self.notify(f"关闭监控: {title[:30]}")
            with contextlib.suppress(AttributeError):
                self.screen.refresh_sidebar_counts()
            with contextlib.suppress(Exception):
                table = self.query_one("#monitor-table", DataTable)
                table.remove_row(eid)
                self._monitored = [
                    m for m in self._monitored if m["event"].event_id != eid
                ]

        self.app.push_screen(ConfirmUnmonitorModal(title), _on_dismiss)

    def refresh_data(self) -> None:
        """Re-read from DB and refresh mutable columns in-place."""
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

            # next check
            next_check_str = format_next_check(new.get("next_check_at"))
            with contextlib.suppress(Exception):
                table.update_cell(eid, "next_check", next_check_str)

            # ai version
            ai_str = format_ai_version(new.get("analysis_count", 0))
            with contextlib.suppress(Exception):
                table.update_cell(eid, "ai", ai_str)

            # movement
            mov = new.get("movement")
            movement_str = (
                format_movement(mov["label"], mov["magnitude"], mov["quality"])
                if mov else "—"
            )
            with contextlib.suppress(Exception):
                table.update_cell(eid, "movement", movement_str)

            # settlement window — min/max end_date may have shifted as
            # sub-markets resolve.
            settlement_str = format_settlement_range(
                new.get("markets_end_min"), new.get("markets_end_max"),
            )
            with contextlib.suppress(Exception):
                table.update_cell(eid, "settlement", settlement_str)

        self._monitored = [e for e in events if e["is_monitored"]]
