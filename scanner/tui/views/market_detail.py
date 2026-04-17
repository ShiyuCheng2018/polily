"""MarketDetailView: event detail page composed from reusable components."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from scanner.tui.components import (
    AnalysisPanel,
    EventHeader,
    EventKpiRow,
    PositionPanel,
    SubMarketTable,
)

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
# MarketDetailView
# ---------------------------------------------------------------------------


class MarketDetailView(Widget):
    """Event detail dashboard composed from reusable components."""

    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("backspace", "go_back", show=False),
        Binding("a", "analyze", "AI分析"),
        Binding("t", "trade", "交易"),
        Binding("m", "toggle_monitor", "监控"),
        Binding("v", "switch_version", "版本"),
        Binding("o", "open_link", "链接"),
    ]

    DEFAULT_CSS = """
    MarketDetailView { height: 1fr; }
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
            yield EventHeader(event, monitor, movements)
            yield EventKpiRow(event, markets)
            yield SubMarketTable(markets, event)
            yield Static("")
            yield PositionPanel(trades, markets, movements)

            if analyses or self._analyzing:
                yield Static("")
                yield AnalysisPanel(analyses, self._version_idx, self._analyzing)
            elif not self._analyzing:
                yield Static("")
                yield Static("[dim]按 a 启动 AI 分析[/dim]", classes="row")

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
        self.service.toggle_monitor(self.event_id, enable=not currently_on)
        state = "OFF" if currently_on else "ON"
        self.notify(f"监控 {state}")
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
