"""EventDetailView: event detail page composed from reusable components.

v0.8.0 migration:
- PolilyZone atoms for 事件信息 / 市场 / 持仓 / 叙事分析 sections
- EventBus subscription (TOPIC_PRICE_UPDATED, TOPIC_POSITION_UPDATED)
- `r` (刷新) binding added
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from scanner.core.events import TOPIC_POSITION_UPDATED, TOPIC_PRICE_UPDATED
from scanner.tui.components import (
    AnalysisPanel,
    BinaryMarketStructurePanel,
    EventHeader,
    EventKpiRow,
    PositionPanel,
    SubMarketTable,
)
from scanner.tui.icons import ICON_AUTO_MONITOR, ICON_EVENT, ICON_MARKET, ICON_POSITION
from scanner.tui.widgets.polily_zone import PolilyZone

if TYPE_CHECKING:
    from scanner.tui.service import ScanService


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class BackToList(Message):
    pass


class AnalyzeRequested(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class CancelAnalysisRequested(Message):
    pass


class RescoreEventRequested(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class SwitchVersionRequested(Message):
    def __init__(self, event_id: str, version_idx: int):
        super().__init__()
        self.event_id = event_id
        self.version_idx = version_idx


# ---------------------------------------------------------------------------
# EventDetailView
# ---------------------------------------------------------------------------


class EventDetailView(Widget):
    """Event detail dashboard composed from reusable components."""

    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("backspace", "go_back", show=False),
        Binding("a", "analyze", "AI分析"),
        Binding("t", "trade", "交易"),
        Binding("m", "toggle_monitor", "监控"),
        Binding("v", "switch_version", "版本"),
        Binding("o", "open_link", "链接"),
        Binding("r", "refresh", "刷新", show=True),  # v0.8.0
    ]

    DEFAULT_CSS = """
    EventDetailView { height: 1fr; }
    EventDetailView > VerticalScroll { height: 1fr; }
    EventDetailView > VerticalScroll > PolilyZone { height: auto; }
    """

    def __init__(
        self,
        event_id: str,
        service: ScanService,
        *,
        analyzing: bool = False,
        version_idx: int | None = None,
    ):
        super().__init__()
        self.event_id = event_id
        self.service = service
        self._analyzing = analyzing
        self._requested_version_idx = version_idx
        self._detail = self.service.get_event_detail(self.event_id)
        self._version_idx: int = -1

        if self._detail is not None:
            analyses = self._detail.get("analyses", [])
            if analyses:
                if (
                    self._requested_version_idx is not None
                    and 0 <= self._requested_version_idx < len(analyses)
                ):
                    self._version_idx = self._requested_version_idx
                else:
                    self._version_idx = len(analyses) - 1

    def compose(self) -> ComposeResult:
        d = self._detail or {}
        event = d.get("event")
        markets = d.get("markets", [])
        analyses = d.get("analyses", [])
        trades = d.get("trades", [])
        movements = d.get("movements", [])
        monitor = d.get("monitor")

        with VerticalScroll():
            # Zone: 事件信息 (header + KPI row)
            with PolilyZone(title=f"{ICON_EVENT} 事件信息", id="event-info-zone"):
                yield EventHeader(event, monitor, movements)
                yield EventKpiRow(event, markets)

            # Zone: 市场 (structure panel or sub-market table)
            with PolilyZone(title=f"{ICON_MARKET} 市场", id="market-zone"):
                if len(markets) == 1:
                    yield BinaryMarketStructurePanel(markets[0], event)
                else:
                    yield SubMarketTable(markets, event)

            # Zone: 持仓
            with PolilyZone(title=f"{ICON_POSITION} 持仓", id="position-zone"):
                yield PositionPanel(trades, markets, movements)

            # Zone: 叙事分析 (only when analyses exist or analysis in progress)
            if analyses or self._analyzing:
                with PolilyZone(title=f"{ICON_AUTO_MONITOR} 叙事分析", id="analysis-zone"):
                    yield AnalysisPanel(analyses, self._version_idx, self._analyzing)
            else:
                yield Static("[dim]按 a 启动 AI 分析[/dim]", classes="row")

    # ------------------------------------------------------------------
    # Lifecycle — bus subscription
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Subscribe to price + position bus topics for auto-refresh."""
        self.service.event_bus.subscribe(TOPIC_PRICE_UPDATED, self._on_price_update)
        self.service.event_bus.subscribe(TOPIC_POSITION_UPDATED, self._on_position_update)

    def on_unmount(self) -> None:
        """Clean up bus subscriptions."""
        self.service.event_bus.unsubscribe(TOPIC_PRICE_UPDATED, self._on_price_update)
        self.service.event_bus.unsubscribe(TOPIC_POSITION_UPDATED, self._on_position_update)

    def _on_price_update(self, payload: dict) -> None:
        """Bus callback — MUST use call_from_thread (called from non-UI thread)."""
        if payload.get("event_id") == self.event_id:
            self.app.call_from_thread(self.refresh_data)

    def _on_position_update(self, payload: dict) -> None:
        """Bus callback — MUST use call_from_thread (called from non-UI thread)."""
        self.app.call_from_thread(self.refresh_data)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def refresh_data(self) -> None:
        """Re-fetch data from DB and recompose the view."""
        new_detail = self.service.get_event_detail(self.event_id)
        if new_detail is None:
            return
        self._detail = new_detail
        # Preserve analysis version selection
        analyses = self._detail.get("analyses", [])
        if analyses and 0 <= self._version_idx < len(analyses):
            pass  # keep current
        elif analyses:
            self._version_idx = len(analyses) - 1
        self.recompose()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_refresh(self) -> None:
        """Manual refresh — re-fetch data and recompose the view."""
        self.refresh_data()

    def action_go_back(self) -> None:
        if self._analyzing:
            self.post_message(CancelAnalysisRequested())
        else:
            self.post_message(BackToList())

    def action_analyze(self) -> None:
        if self._analyzing:
            return
        self._analyzing = True
        self.post_message(AnalyzeRequested(self.event_id))

    def action_trade(self) -> None:
        markets = self._detail.get("markets", []) if self._detail else []
        if not markets:
            self.notify("无可交易市场")
            return
        # Trading requires an active monitor — positions on an unmonitored
        # event would drift without price polling / narrator attention,
        # silently rotting until the user toggles monitor back on. Block
        # here with a clear toast rather than letting the modal open.
        monitor = self._detail.get("monitor") if self._detail else None
        if not (monitor and monitor.get("auto_monitor")):
            self.notify(
                "需要先激活监控才能进行交易 — 按 m 开启监控",
                severity="warning",
            )
            return
        from scanner.tui.views.trade_dialog import TradeDialog

        def _on_dismiss(payload: dict | None) -> None:
            # Post-v0.6.0: payload is a dict from TradeDialog with action/side/shares/etc.
            # Truthy on success (any completed buy/sell), None on cancel.
            if payload:
                self.screen.refresh_sidebar_counts()
                self.refresh_data()

        self.app.push_screen(TradeDialog(self.event_id, markets, self.service), _on_dismiss)

    def action_toggle_monitor(self) -> None:
        monitor = self._detail.get("monitor") if self._detail else None
        currently_on = bool(monitor and monitor.get("auto_monitor"))

        if not currently_on:
            # Enabling is non-destructive — no confirmation needed.
            self.service.toggle_monitor(self.event_id, enable=True)
            self._after_monitor_change("ON")
            return

        # Disabling path: block if positions exist, otherwise confirm.
        pos_count = self.service.get_event_position_count(self.event_id)
        if pos_count > 0:
            self.notify(
                f"无法取消监控 — 该事件有 {pos_count} 个持仓未结算，"
                "请先平仓或等待结算",
                severity="warning",
            )
            return

        from scanner.tui.views.monitor_modals import ConfirmUnmonitorModal

        event = self._detail.get("event") if self._detail else None
        event_title = event.title if event else self.event_id

        def _on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self.service.toggle_monitor(self.event_id, enable=False)
                self._after_monitor_change("OFF")

        self.app.push_screen(ConfirmUnmonitorModal(event_title), _on_dismiss)

    def _after_monitor_change(self, state: str) -> None:
        """Post-toggle side effects shared by enable + confirmed-disable."""
        self.notify(f"监控 {state}")
        with contextlib.suppress(AttributeError):
            self.screen.refresh_sidebar_counts()
        self.post_message(SwitchVersionRequested(self.event_id, self._version_idx))

    def action_switch_version(self) -> None:
        analyses = self._detail.get("analyses", []) if self._detail else []
        if not analyses:
            self.notify("无分析版本")
            return
        next_idx = (self._version_idx + 1) % len(analyses)
        self.post_message(SwitchVersionRequested(self.event_id, next_idx))

    def action_open_link(self) -> None:
        event = self._detail.get("event") if self._detail else None
        if event and event.slug:
            import webbrowser
            url = f"https://polymarket.com/event/{event.slug}"
            try:
                webbrowser.open(url)
            except Exception:
                self.notify("无法打开浏览器", severity="warning")
        else:
            self.notify("无链接信息", severity="warning")
