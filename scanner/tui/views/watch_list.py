"""MonitorListView: shows all markets with auto_monitor enabled."""

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.market_state import MarketState

_STATUS_LABELS = {
    "buy_yes": "持YES",
    "buy_no": "持NO",
    "watch": "观察",
    "closed": "已结算",
    "pass": "已放弃",
}


class ViewMonitorDetail(Message):
    """Request to view a monitored market's detail."""
    def __init__(self, market_id: str):
        super().__init__()
        self.market_id = market_id


class MonitorListView(Widget):
    """Monitor list showing all auto_monitor=1 markets regardless of status."""

    BINDINGS = [
        ("enter", "view_detail", "查看详情"),
    ]

    DEFAULT_CSS = """
    MonitorListView { height: 1fr; }
    MonitorListView #monitor-title { padding: 1 0 0 0; text-style: bold; }
    MonitorListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, monitored: dict[str, MarketState]):
        super().__init__()
        sorted_items = sorted(monitored.items(), key=lambda x: x[1].updated_at, reverse=True)
        self._monitored = dict(sorted_items)
        self._market_ids = list(self._monitored.keys())

    def compose(self) -> ComposeResult:
        yield Static(f" 监控列表 ({len(self._monitored)})", id="monitor-title")
        if not self._monitored:
            yield Static(" 监控列表为空。在市场详情页按 m 开启自动监控。", classes="empty-msg")
        else:
            yield DataTable(id="monitor-table")

    def on_mount(self) -> None:
        if not self._monitored:
            return
        try:
            table = self.query_one("#monitor-table", DataTable)
        except Exception:
            return
        table.cursor_type = "row"
        table.add_columns("状态", "市场", "下次检查")
        for mid, state in self._monitored.items():
            status_label = _STATUS_LABELS.get(state.status, state.status)
            title = state.title[:35] if state.title else mid[:20]
            from scanner.tui.utils import format_countdown
            next_check = format_countdown(state.next_check_at)
            table.add_row(status_label, title, next_check, key=mid)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.post_message(ViewMonitorDetail(event.row_key.value))
