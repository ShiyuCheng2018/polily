"""MarketListView: event-first research list."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.service import ScanService


class ViewDetailRequested(Message):
    """Request to view event detail."""

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class MarketListView(Widget):
    """Event-first research list."""

    BINDINGS = [
        Binding("enter", "view_detail", "详情"),
        Binding("p", "quick_pass", "PASS"),
        Binding("m", "toggle_monitor", "监控"),
        Binding("o", "open_link", "打开链接"),
    ]

    DEFAULT_CSS = """
    MarketListView { height: 1fr; }
    MarketListView #list-title { padding: 1 0 0 0; text-style: bold; }
    MarketListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, events: list[dict], service: ScanService, title: str = "研究列表"):
        super().__init__()
        self.events = events  # list of EventSummary dicts
        self.service = service
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(f" {self._title} ({len(self.events)})", id="list-title")
        if not self.events:
            yield Static(" 暂无事件。运行扫描 (s) 获取市场数据。", classes="empty-msg")
        else:
            yield DataTable(id="market-table")

    def on_mount(self) -> None:
        if not self.events:
            return
        table = self.query_one("#market-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("事件", "子市场", "评分", "状态", "价格", "结算", "类型")

        for e in self.events:
            ev = e["event"]
            mc = e["market_count"]
            score = f"{ev.structure_score:.0f}" if ev.structure_score else "-"

            # Status labels
            labels: list[str] = []
            if ev.user_status == "pass":
                labels.append("[PASS]")
            if e["is_monitored"]:
                labels.append("[监控]")
            if e["has_position"]:
                labels.append("[持仓]")
            status = " ".join(labels) or "-"

            # Title (truncate)
            title = ev.title[:42] + ("..." if len(ev.title) > 42 else "")

            # Sub-market info
            if mc > 1:
                sub_info = f"{mc} 个"
                if e.get("leader_title"):
                    sub_info += f" ({e['leader_title'][:15]})"
            else:
                sub_info = "二元"

            # Price
            if e.get("leader_price"):
                price_str = f"{e['leader_price']:.2f}"
            else:
                price_str = "-"

            # Resolution time
            from scanner.tui.utils import format_countdown

            days = format_countdown(ev.end_date)

            table.add_row(
                title,
                sub_info,
                score,
                status,
                price_str,
                days,
                ev.market_type or "other",
                key=ev.event_id,
            )

    def _get_selected_event(self) -> dict | None:
        if not self.events:
            return None
        try:
            table = self.query_one("#market-table", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row >= len(self.events):
            return None
        return self.events[row]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        e = self._get_selected_event()
        if e:
            self.post_message(ViewDetailRequested(e["event"].event_id))

    def action_view_detail(self) -> None:
        e = self._get_selected_event()
        if e:
            self.post_message(ViewDetailRequested(e["event"].event_id))

    def action_quick_pass(self) -> None:
        e = self._get_selected_event()
        if not e:
            return
        self.service.pass_event(e["event"].event_id)
        self.notify(f"PASS: {e['event'].title[:30]}")
        self.screen.refresh_sidebar_counts()

    def action_toggle_monitor(self) -> None:
        e = self._get_selected_event()
        if not e:
            return
        currently = e["is_monitored"]
        self.service.toggle_monitor(e["event"].event_id, enable=not currently)
        action = "关闭监控" if currently else "开启监控"
        self.notify(f"{action}: {e['event'].title[:30]}")
        self.screen.refresh_sidebar_counts()

    def action_open_link(self) -> None:
        e = self._get_selected_event()
        if e:
            import webbrowser

            slug = e["event"].slug or e["event"].event_id
            try:
                webbrowser.open(f"https://polymarket.com/event/{slug}")
            except Exception:
                self.notify("无法打开浏览器", severity="warning")
