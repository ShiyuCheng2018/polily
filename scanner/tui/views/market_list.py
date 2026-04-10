"""MarketListView: event-first research list with probability distribution."""

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
    """Event-first research list with fold/expand for multi-outcome events."""

    BINDINGS = [
        Binding("enter", "view_detail", "详情"),
        Binding("space", "toggle_expand", "展开/收起"),
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
        self.events = events
        self.service = service
        self._title = title
        self._expanded: set[str] = set()  # event_ids currently expanded
        self._row_map: list[dict] = []  # maps row index to event/sub-market data

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
        table.add_columns("", "事件", "评分", "价格", "结算", "类型", "状态")
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """Rebuild all table rows based on current expand state."""
        try:
            table = self.query_one("#market-table", DataTable)
        except Exception:
            return

        table.clear()
        self._row_map = []

        from scanner.tui.utils import format_countdown

        for e in self.events:
            ev = e["event"]
            mc = e["market_count"]
            score = f"{ev.structure_score:.0f}" if ev.structure_score else "-"
            is_expanded = ev.event_id in self._expanded
            is_multi = mc > 1

            # Status labels
            labels: list[str] = []
            if ev.user_status == "pass":
                labels.append("[PASS]")
            if e["is_monitored"]:
                labels.append("[监控]")
            if e["has_position"]:
                labels.append("[持仓]")
            status = " ".join(labels) or ""

            # Price info
            if is_multi:
                leader = e.get("leader_title", "")
                price = e.get("leader_price")
                price_str = f"{leader[:12]} @{price:.0%}" if leader and price else "-"
            else:
                price = e.get("leader_price")
                price_str = f"YES {price:.2f}" if price else "-"

            # Resolution
            days = format_countdown(ev.end_date)

            # Expand indicator
            if is_multi:
                prefix = "▼" if is_expanded else "▶"
                prefix += f" ({mc})"
            else:
                prefix = "  "

            title = ev.title[:38] + ("..." if len(ev.title) > 38 else "")

            table.add_row(
                prefix, title, score, price_str, days,
                ev.market_type or "other", status,
                key=f"ev_{ev.event_id}",
            )
            self._row_map.append({"type": "event", "event": e})

            # If expanded, show sub-markets with probability bars
            if is_expanded and is_multi:
                self._add_sub_market_rows(table, ev.event_id)

    def _add_sub_market_rows(self, table: DataTable, event_id: str) -> None:
        """Insert sub-market rows for an expanded event."""
        from scanner.core.event_store import get_event_markets

        markets = get_event_markets(event_id, self.service.db)
        # Sort by YES price descending, exclude closed
        active = [m for m in markets if not m.closed]
        active.sort(key=lambda m: m.yes_price or 0, reverse=True)

        for i, m in enumerate(active[:10]):  # Show top 10
            label = m.group_item_title or m.question[:20]
            price = m.yes_price or 0

            # Probability bar using block chars
            bar_len = int(price * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)

            is_last = i == min(len(active), 10) - 1
            connector = "└" if is_last else "├"

            table.add_row(
                f"  {connector}", f"  {label[:28]}", "", f"{bar} {price:.0%}", "", "", "",
                key=f"sub_{m.market_id}",
            )
            self._row_map.append({"type": "sub_market", "market": m, "event_id": event_id})

        if len(active) > 10:
            table.add_row(
                "  └", f"  ... 还有 {len(active) - 10} 个", "", "", "", "", "",
                key=f"more_{event_id}",
            )
            self._row_map.append({"type": "more", "event_id": event_id})

    def _get_selected(self) -> dict | None:
        try:
            table = self.query_one("#market-table", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row < 0 or row >= len(self._row_map):
            return None
        return self._row_map[row]

    def _get_selected_event(self) -> dict | None:
        """Get the event dict for the selected row (works for both event and sub-market rows)."""
        item = self._get_selected()
        if not item:
            return None
        if item["type"] == "event":
            return item["event"]
        if item["type"] in ("sub_market", "more"):
            # Find parent event
            eid = item.get("event_id")
            for e in self.events:
                if e["event"].event_id == eid:
                    return e
        return None

    def action_toggle_expand(self) -> None:
        """Toggle expand/collapse for multi-outcome event."""
        item = self._get_selected()
        if not item:
            return
        if item["type"] == "event":
            ev = item["event"]["event"]
            if item["event"]["market_count"] <= 1:
                return  # binary, nothing to expand
            if ev.event_id in self._expanded:
                self._expanded.discard(ev.event_id)
            else:
                self._expanded.add(ev.event_id)
            self._rebuild_table()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter on row — detail for events, toggle for multi-outcome."""
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
