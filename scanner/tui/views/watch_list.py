"""WatchListView: actionable watch list with trigger conditions."""

from textual.app import ComposeResult
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

    BINDINGS = []

    DEFAULT_CSS = """
    WatchListView { height: 1fr; }
    WatchListView #watch-title { padding: 1 0 0 0; text-style: bold; }
    WatchListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, watched: dict[str, MarketState]):
        super().__init__()
        # Sort: items with trigger conditions first, then by updated_at desc
        def sort_key(item):
            _mid, state = item
            has_trigger = bool(state.wc_trigger_event)
            return (has_trigger, state.updated_at)

        sorted_items = sorted(watched.items(), key=sort_key, reverse=True)
        self._watched = dict(sorted_items)
        self._market_ids = list(self._watched.keys())

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
        table.add_columns("市场", "原因", "下次检查", "触发条件", "#", "自动")
        for mid, state in self._watched.items():
            title = state.title[:30] if state.title else mid[:20]
            reason = (state.wc_watch_reason or state.watch_reason or "-")[:25]
            next_check = state.next_check_at[:16] if state.next_check_at else "-"
            trigger = (state.wc_trigger_event or "-")[:20]
            seq = str(state.watch_sequence)
            auto = "ON" if state.auto_monitor else "-"
            table.add_row(title, reason, next_check, trigger, seq, auto, key=mid)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.post_message(ViewWatchDetail(event.row_key.value))
