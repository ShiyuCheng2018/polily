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
            has_trigger = bool(state.watch_conditions and state.watch_conditions.trigger_event)
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
        table.add_columns("市场", "原因", "触发条件", "更优价格", "失效")
        for mid, state in self._watched.items():
            title = state.title[:30] if state.title else mid[:20]
            wc = state.watch_conditions
            if wc:
                reason = wc.watch_reason[:25] if wc.watch_reason else "-"
                trigger = wc.trigger_event[:20] if wc.trigger_event else "-"
                entry = wc.better_entry if wc.better_entry else "-"
                invalid = wc.invalidation[:15] if wc.invalidation else "-"
            else:
                reason = trigger = entry = invalid = "-"
            table.add_row(title, reason, trigger, entry, invalid, key=mid)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.row_key and event.row_key.value:
            self.post_message(ViewWatchDetail(event.row_key.value))
