"""WatchListView: actionable watch list with trigger conditions."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.market_state import MarketState


class ViewWatchDetail(Message):
    """Request to view a watched market's detail."""
    def __init__(self, market_id: str):
        super().__init__()
        self.market_id = market_id


class WatchListView(Widget):
    """Watch list with trigger conditions and better entry prices."""

    BINDINGS = [
        Binding("enter", "view_detail", show=False),
    ]

    DEFAULT_CSS = """
    WatchListView { height: 1fr; }
    WatchListView #watch-title { padding: 1 0 0 0; text-style: bold; }
    WatchListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, watched: dict[str, MarketState]):
        super().__init__()
        self._watched = watched
        self._market_ids = list(watched.keys())

    def compose(self) -> ComposeResult:
        yield Static(f" 观察列表 ({len(self._watched)})", id="watch-title")
        if not self._watched:
            yield Static(" 观察列表为空。在市场详情页按 w 添加。", classes="empty-msg")
        else:
            yield DataTable(id="watch-table")

    def on_mount(self) -> None:
        if not self._watched:
            return
        try:
            table = self.query_one("#watch-table", DataTable)
        except Exception:
            return
        table.cursor_type = "row"
        table.add_columns("市场 ID", "原因", "触发条件", "更优价格", "失效")
        for mid, state in self._watched.items():
            wc = state.watch_conditions
            if wc:
                reason = wc.watch_reason[:30] if wc.watch_reason else "-"
                trigger = wc.trigger_event[:25] if wc.trigger_event else "-"
                entry = wc.better_entry if wc.better_entry else "-"
                invalid = wc.invalidation[:20] if wc.invalidation else "-"
            else:
                reason = trigger = entry = invalid = "-"
            table.add_row(mid[:20], reason, trigger, entry, invalid, key=mid)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        try:
            table = self.query_one("#watch-table", DataTable)
            row_idx = table.cursor_row
        except Exception:
            return
        if row_idx < len(self._market_ids):
            self.post_message(ViewWatchDetail(self._market_ids[row_idx]))
