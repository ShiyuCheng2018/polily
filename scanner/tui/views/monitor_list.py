"""MonitorListView: shows events with active monitoring.

Role: answer "what am I monitoring, and when's the next poll?" plus a few
routing hints (structure score, AI analysis version, latest movement
signal). Trade / position / P&L details live on their respective pages.

v0.8.0 migration:
- PolilyZone atom wraps the list (title: 监控列表)
- Chinese labels for 状态 column removed; status implied by membership
- EventBus subscription (TOPIC_MONITOR_UPDATED, TOPIC_PRICE_UPDATED,
  TOPIC_SCAN_UPDATED) for auto-refresh on mutations
- Q11 NAV_BINDINGS + view-specific bindings (enter, m, r)
"""

import contextlib

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
from scanner.tui.icons import ICON_AUTO_MONITOR
from scanner.tui.monitor_format import (
    format_ai_version,
    format_movement,
    format_next_check,
    format_settlement_range,
)
from scanner.tui.service import ScanService
from scanner.tui.widgets.polily_zone import PolilyZone


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
        Binding("enter", "view_detail", "详情", show=True),
        Binding("m", "toggle_monitor", "关闭监控", show=True),
        Binding("r", "refresh", "刷新", show=True),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    MonitorListView { height: 1fr; }
    MonitorListView > VerticalScroll { height: 1fr; }
    /* v0.8.0+: stretch zone + table to screen bottom (match paper_status/history/archived). */
    MonitorListView > VerticalScroll > PolilyZone { height: 1fr; }
    MonitorListView DataTable { height: 1fr; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._monitored: list[dict] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PolilyZone(
                title=f"{ICON_AUTO_MONITOR} 监控列表",
                id="monitor-zone",
            )

    def on_mount(self):
        # Mount the DataTable ONCE inside the zone. `_render_all` then
        # refreshes it in place via `table.clear()` + re-add rows.
        # Re-mounting per render would leak stale widgets because
        # Textual's `remove()` is deferred, tripping DuplicateIds on
        # `#monitor-table` when the user manually hits `r`.
        try:
            zone = self.query_one("#monitor-zone", PolilyZone)
        except Exception:
            zone = None
        if zone is not None:
            table = DataTable(id="monitor-table")
            zone.mount(table)
            table.cursor_type = "row"
            table.add_columns(*_COLUMN_SPEC)

        self.service.event_bus.subscribe(
            TOPIC_MONITOR_UPDATED, self._on_monitor_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_SCAN_UPDATED, self._on_scan_update,
        )
        self._render_all()

    def on_unmount(self):
        self.service.event_bus.unsubscribe(
            TOPIC_MONITOR_UPDATED, self._on_monitor_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_SCAN_UPDATED, self._on_scan_update,
        )

    # -- Bus callbacks (published from non-UI threads — must hop back) --

    def _on_monitor_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    def _on_price_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    def _on_scan_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    # -- Rendering --

    def _render_all(self) -> None:
        """Refresh the DataTable rows from fresh service data (in place).

        The table itself is mounted once in `on_mount`; this method only
        clears and repopulates rows so manual `r` refresh doesn't race
        Textual's deferred remove.
        """
        try:
            table = self.query_one("#monitor-table", DataTable)
        except Exception:
            return

        events = self.service.get_all_events()
        self._monitored = [e for e in events if e["is_monitored"]]

        table.clear()

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
        if not self._monitored:
            return None
        try:
            table = self.query_one("#monitor-table", DataTable)
            row = table.cursor_row
            if row is None or row >= len(self._monitored):
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

    def action_refresh(self):
        self._render_all()

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
        """Re-read from DB and refresh mutable columns in-place.

        Kept as a public API for callers that want a lightweight in-place
        update without rebuilding the table (e.g. the main screen's periodic
        refresh tick). `_render_all` is the bus-driven full rebuild path.
        """
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
