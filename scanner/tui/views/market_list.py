"""MarketListView: event-first research list with fold/expand + probability bars.

v0.8.0 migration:
- PolilyZone atom wraps the list (title: 研究列表)
- EventBus subscription (TOPIC_PRICE_UPDATED, TOPIC_MONITOR_UPDATED,
  TOPIC_SCAN_UPDATED) for auto-refresh on mutations
- Q11 NAV_BINDINGS + view-specific bindings (enter, p, m, o, r)
- Chinese labels throughout; internal event_id not surfaced
"""

import contextlib
from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable

from scanner.core.events import (
    TOPIC_MONITOR_UPDATED,
    TOPIC_PRICE_UPDATED,
    TOPIC_SCAN_UPDATED,
)
from scanner.tui.bindings import NAV_BINDINGS
from scanner.tui.icons import ICON_EVENT
from scanner.tui.service import ScanService
from scanner.tui.widgets.polily_zone import PolilyZone


class ViewDetailRequested(Message):
    """Request to view event detail."""

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


def _fmt_volume(vol: float | None) -> str:
    """Format volume: $1.5M, $340K, $2.1K."""
    if not vol or vol <= 0:
        return "-"
    if vol >= 1_000_000:
        return f"${vol / 1_000_000:.1f}M"
    if vol >= 1_000:
        return f"${vol / 1_000:.0f}K"
    return f"${vol:.0f}"


_COLUMN_SPEC = [
    ("事件", "title"),
    ("评分", "score"),
    ("概况", "summary"),
    ("交易量", "volume"),
    ("结算", "countdown"),
    ("类型", "type"),
    ("状态", "status"),
]


class MarketListView(Widget):
    """Event-first research list with fold/expand for multi-outcome events."""

    BINDINGS = [
        Binding("enter", "open_detail", "详情", show=True),
        Binding("p", "quick_pass", "PASS", show=True),
        Binding("m", "toggle_monitor", "监控", show=True),
        Binding("o", "open_link", "打开链接", show=True),
        Binding("r", "refresh", "刷新", show=False),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    MarketListView { height: 1fr; }
    MarketListView > VerticalScroll { height: 1fr; }
    MarketListView > VerticalScroll > PolilyZone { height: auto; }
    MarketListView DataTable { height: auto; }
    MarketListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(
        self,
        events: list[dict],
        service: ScanService,
        title: str = "研究列表",
    ):
        super().__init__()
        self.events = events
        self.service = service
        self._title = title
        self._expanded: set[str] = set()
        self._row_map: list[dict] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PolilyZone(
                title=f"{ICON_EVENT} {self._title} ({len(self.events)})",
                id="market-list-zone",
            )

    def on_mount(self) -> None:
        self.service.event_bus.subscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_MONITOR_UPDATED, self._on_monitor_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_SCAN_UPDATED, self._on_scan_update,
        )
        self._render_all()

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_MONITOR_UPDATED, self._on_monitor_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_SCAN_UPDATED, self._on_scan_update,
        )

    # -- Bus callbacks (published from non-UI threads — must hop back) --

    def _on_price_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    def _on_monitor_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    def _on_scan_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    # -- Rendering --

    def _render_all(self) -> None:
        """Rebuild the DataTable inside PolilyZone from current self.events."""
        try:
            zone = self.query_one("#market-list-zone", PolilyZone)
        except Exception:
            return

        # Clear any existing content inside zone (table + empty msg).
        for child in list(zone.children):
            # Keep the title static child (it has polily-zone-title class).
            if "polily-zone-title" in child.classes:
                continue
            child.remove()

        if not self.events:
            from textual.widgets import Static

            zone.mount(Static(" 暂无事件。运行扫描 (s) 获取市场数据。", classes="empty-msg"))
            self._row_map = []
            return

        table = DataTable(id="market-table")
        zone.mount(table)
        table.cursor_type = "row"
        table.add_columns(*_COLUMN_SPEC)
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

            # Status labels (Chinese)
            labels: list[str] = []
            if ev.user_status == "pass":
                labels.append("[PASS]")
            if e["is_monitored"]:
                labels.append("[监控]")
            if e["has_position"]:
                labels.append("[持仓]")
            status = " ".join(labels) or ""

            # Title with expand indicator
            if is_multi:
                prefix = "▼" if is_expanded else "▶"
                title = f"{prefix} {ev.title[:36]}" + (
                    "..." if len(ev.title) > 36 else ""
                )
            else:
                title = f"  {ev.title[:38]}" + (
                    "..." if len(ev.title) > 38 else ""
                )

            # Summary (概况) — market count + expired count
            if is_multi:
                closed_count = self.service.db.conn.execute(
                    "SELECT COUNT(*) FROM markets WHERE event_id=? AND closed=1",
                    (ev.event_id,),
                ).fetchone()[0]
                if closed_count > 0:
                    summary = f"{mc}个市场 ({closed_count}个过期)"
                else:
                    summary = f"{mc}个市场"
            else:
                price = e.get("leader_price")
                if price:
                    summary = f"YES {price:.0%} / NO {1 - price:.0%}"
                else:
                    summary = "-"

            vol = _fmt_volume(ev.volume)

            # Resolution — range for multi-outcome, single for binary
            if is_multi:
                from scanner.tui.utils import format_countdown_range

                now_iso = datetime.now(UTC).isoformat()
                r = self.service.db.conn.execute(
                    "SELECT MIN(end_date), MAX(end_date) FROM markets "
                    "WHERE event_id=? AND closed=0 AND end_date IS NOT NULL "
                    "AND end_date > ?",
                    (ev.event_id, now_iso),
                ).fetchone()
                days = format_countdown_range(
                    r[0] if r else None, r[1] if r else None,
                )
            else:
                days = format_countdown(ev.end_date)

            table.add_row(
                title, score, summary, vol, days,
                ev.market_type or "other", status,
                key=f"ev_{ev.event_id}",
            )
            self._row_map.append({"type": "event", "event": e})

            # Expanded sub-markets
            if is_expanded and is_multi:
                self._add_sub_market_rows(table, ev.event_id)

    def _add_sub_market_rows(self, table: DataTable, event_id: str) -> None:
        """Insert sub-market rows for an expanded event."""
        from scanner.core.event_store import get_event_markets

        markets = get_event_markets(event_id, self.service.db)
        active = [m for m in markets if not m.closed]
        # Keep original order (group_item_threshold) — shows natural distribution
        active.sort(key=lambda m: m.group_item_threshold or "999")

        for i, m in enumerate(active):
            label = m.group_item_title or m.question[:20]
            price = m.yes_price or 0

            bar_len = int(price * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)

            is_last = i == len(active) - 1
            connector = "└" if is_last else "├"

            vol = _fmt_volume(m.volume)

            from scanner.tui.utils import format_countdown

            market_date = format_countdown(m.end_date) if m.end_date else ""

            table.add_row(
                f"  {connector} {label[:28]}", "", f"{bar} {price:.0%}", vol,
                market_date, "", "",
                key=f"sub_{m.market_id}",
            )
            self._row_map.append(
                {"type": "sub_market", "market": m, "event_id": event_id}
            )

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
        item = self._get_selected()
        if not item:
            return None
        if item["type"] == "event":
            return item["event"]
        if item["type"] in ("sub_market", "more"):
            eid = item.get("event_id")
            for e in self.events:
                if e["event"].event_id == eid:
                    return e
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter/click: event row → toggle expand (multi) or detail (binary)."""
        item = self._get_selected()
        if not item:
            return
        if item["type"] == "event":
            ev = item["event"]
            if ev["market_count"] > 1:
                # Multi-outcome: toggle expand
                eid = ev["event"].event_id
                if eid in self._expanded:
                    self._expanded.discard(eid)
                else:
                    self._expanded.add(eid)
                self._rebuild_table()
            else:
                # Binary: go to detail
                self.post_message(ViewDetailRequested(ev["event"].event_id))
        elif item["type"] in ("sub_market", "more"):
            # Sub-market or "more": go to event detail
            eid = item.get("event_id")
            if eid:
                self.post_message(ViewDetailRequested(eid))

    def action_open_detail(self) -> None:
        item = self._get_selected()
        if not item:
            return
        if item["type"] == "event":
            ev = item["event"]
            if ev["market_count"] > 1:
                eid = ev["event"].event_id
                if eid in self._expanded:
                    self._expanded.discard(eid)
                else:
                    self._expanded.add(eid)
                self._rebuild_table()
            else:
                self.post_message(ViewDetailRequested(ev["event"].event_id))
        elif item["type"] in ("sub_market", "more"):
            eid = item.get("event_id")
            if eid:
                self.post_message(ViewDetailRequested(eid))

    def action_quick_pass(self) -> None:
        e = self._get_selected_event()
        if not e:
            return
        self.service.pass_event(e["event"].event_id)
        self.notify(f"PASS: {e['event'].title[:30]}")
        with contextlib.suppress(AttributeError):
            self.screen.refresh_sidebar_counts()

    def action_toggle_monitor(self) -> None:
        e = self._get_selected_event()
        if not e:
            return
        currently = e["is_monitored"]
        self.service.toggle_monitor(e["event"].event_id, enable=not currently)
        action = "关闭监控" if currently else "开启监控"
        self.notify(f"{action}: {e['event'].title[:30]}")
        with contextlib.suppress(AttributeError):
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

    def action_refresh(self) -> None:
        """Manual full rebuild (Q11 `r` binding)."""
        self._render_all()

    def refresh_data(self) -> None:
        """Incremental update: re-read DB, update changed cells in-place.

        Kept as a public API for callers that want a lightweight in-place
        update without rebuilding the table. `_render_all` is the
        bus-driven full rebuild path.
        """
        from scanner.core.event_store import get_event_markets

        try:
            table = self.query_one("#market-table", DataTable)
        except Exception:
            return

        # Re-fetch events from DB via the same summary query used by
        # the main menu (get_all_events is the canonical source now).
        fresh = self.service.get_all_events()
        fresh_by_id = {e["event"].event_id: e for e in fresh}

        for e in self.events:
            eid = e["event"].event_id
            new = fresh_by_id.get(eid)
            if not new:
                continue
            new_ev = new["event"]
            # Update event row: score + volume
            score = f"{new_ev.structure_score:.0f}" if new_ev.structure_score else "-"
            with contextlib.suppress(Exception):
                table.update_cell(f"ev_{eid}", "score", score)
                table.update_cell(f"ev_{eid}", "volume", _fmt_volume(new_ev.volume))

            # Update expanded sub-market rows: price bars
            if eid in self._expanded:
                markets = get_event_markets(eid, self.service.db)
                for m in markets:
                    if m.closed:
                        continue
                    price = m.yes_price or 0
                    bar_len = int(price * 20)
                    bar = f"{'█' * bar_len}{'░' * (20 - bar_len)} {price:.0%}"
                    with contextlib.suppress(Exception):
                        table.update_cell(f"sub_{m.market_id}", "summary", bar)

        self.events = fresh
