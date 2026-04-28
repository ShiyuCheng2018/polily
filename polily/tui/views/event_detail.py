"""EventDetailView: event detail page composed from reusable components.

v0.8.0 migration:
- PolilyZone atoms for 事件信息 / 市场 / 持仓 / 叙事分析 sections
- EventBus subscription (TOPIC_PRICE_UPDATED, TOPIC_POSITION_UPDATED)
- `r` (刷新) binding added
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from polily.core.events import (
    TOPIC_LANGUAGE_CHANGED,
    TOPIC_POSITION_UPDATED,
    TOPIC_PRICE_UPDATED,
)
from polily.core.lifecycle import (
    MarketState,
    market_state,
)
from polily.tui._dispatch import dispatch_to_ui, once_per_tick
from polily.tui.components import (
    AnalysisPanel,
    BinaryMarketStructurePanel,
    EventHeader,
    EventKpiRow,
    PositionPanel,
    SubMarketTable,
)
from polily.tui.i18n import t
from polily.tui.icons import ICON_AUTO_MONITOR, ICON_EVENT, ICON_MARKET, ICON_POSITION
from polily.tui.lifecycle_labels import market_state_label_i18n, settled_winner_suffix_i18n
from polily.tui.widgets.polily_zone import PolilyZone

if TYPE_CHECKING:
    from polily.tui.service import PolilyService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _market_zone_title_suffix(markets: list, *, now: datetime | None = None) -> str:
    """Build the market zone border-title suffix showing state breakdown.

    Empty list → '' (caller passes plain market title).
    Single market → '(Trading)' / '(Pending Settlement)' /
                    '(Settled NO won)' etc., translated via lifecycle_labels.
    Multi market → '(Active N, Pending N, Settling N, Settled N)' from
                   event_detail.market_breakdown.full template.
    """
    if not markets:
        return ""

    if len(markets) == 1:
        m = markets[0]
        state = market_state(m, now=now)
        label = market_state_label_i18n(state)
        if state == MarketState.SETTLED:
            label = f"{label}{settled_winner_suffix_i18n(m)}"
        return f"({label})"

    counts = {s: 0 for s in MarketState}
    for m in markets:
        counts[market_state(m, now=now)] += 1
    return t(
        "event_detail.market_breakdown.full",
        active=counts[MarketState.TRADING],
        pending=counts[MarketState.PENDING_SETTLEMENT],
        settling=counts[MarketState.SETTLING],
        settled=counts[MarketState.SETTLED],
    )


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

    # NOTE: I18nFooter renders binding labels via t(f"binding.{action}") at
    # compose time. Action `toggle_monitor` shares its catalog key with
    # monitor_list, so footer shows "Stop Monitor" / "关闭监控" — slightly
    # imprecise on this view (m can also enable monitoring), but consistent
    # cross-view labelling is worth the trade.
    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("backspace", "go_back", show=False),
        Binding("a", "analyze", "AI分析"),
        Binding("t", "trade", "交易"),
        Binding("m", "toggle_monitor", "监控"),
        Binding("v", "switch_version", "版本"),
        Binding("o", "open_link", "链接"),
        Binding("r", "refresh", "刷新", show=True),
    ]

    DEFAULT_CSS = """
    EventDetailView { height: 1fr; }
    EventDetailView > VerticalScroll { height: 1fr; }
    EventDetailView > VerticalScroll > PolilyZone { height: auto; }
    """

    def __init__(
        self,
        event_id: str,
        service: PolilyService,
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
            # Zone: event info (header + KPI row)
            with PolilyZone(title=f"{ICON_EVENT} {t('event_detail.title.event_info')}", id="event-info-zone"):
                yield EventHeader(event, monitor, movements, markets=markets)
                yield EventKpiRow(event, markets)

            # Zone: market (structure panel or sub-market table)
            title = f"{ICON_MARKET} {t('event_detail.title.market')}"
            suffix = _market_zone_title_suffix(markets)
            if suffix:
                title = f"{title} {suffix}"
            with PolilyZone(title=title, id="market-zone"):
                if len(markets) == 1:
                    yield BinaryMarketStructurePanel(markets[0], event)
                else:
                    yield SubMarketTable(markets, event)

            # Zone: position
            with PolilyZone(title=f"{ICON_POSITION} {t('event_detail.title.position')}", id="position-zone"):
                yield PositionPanel(trades, markets, movements)

            # Zone: narrative analysis (only when analyses exist or analysis in progress)
            if analyses or self._analyzing:
                with PolilyZone(title=f"{ICON_AUTO_MONITOR} {t('event_detail.title.analysis')}", id="analysis-zone"):
                    yield AnalysisPanel(analyses, self._version_idx, self._analyzing)
            else:
                yield Static(t("event_detail.empty.analysis"), classes="row")

    # ------------------------------------------------------------------
    # Lifecycle — bus subscription
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        """Subscribe to price + position bus topics for auto-refresh."""
        self.service.event_bus.subscribe(TOPIC_PRICE_UPDATED, self._on_price_update)
        self.service.event_bus.subscribe(TOPIC_POSITION_UPDATED, self._on_position_update)
        self.service.event_bus.subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def on_unmount(self) -> None:
        """Clean up bus subscriptions."""
        self.service.event_bus.unsubscribe(TOPIC_PRICE_UPDATED, self._on_price_update)
        self.service.event_bus.unsubscribe(TOPIC_POSITION_UPDATED, self._on_position_update)
        self.service.event_bus.unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_lang_changed(self, payload: dict) -> None:
        """Recompose so all t() calls in compose() pick up the new language.
        EventDetailView already drives every refresh through recompose, so
        the language switch follows the existing path."""
        dispatch_to_ui(self.app, lambda: self.refresh(recompose=True))

    def _on_price_update(self, payload: dict) -> None:
        """Bus callback — refresh dispatched via `@once_per_tick` decorator.

        A `"source": "heartbeat"` payload is a match-all broadcast
        (MainScreen's 5s bridge for cross-process daemon writes) —
        treat as relevant to this view. Tightening from the pre-v0.8.0
        "event_id is None = match-all" rule so future publishers that
        accidentally omit event_id don't silently refresh every open
        EventDetailView.
        """
        if payload.get("source") == "heartbeat" or payload.get("event_id") == self.event_id:
            self.refresh_data()

    def _on_position_update(self, payload: dict) -> None:
        """Bus callback — dedup'd via `@once_per_tick` on refresh_data."""
        self.refresh_data()

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    @once_per_tick
    def refresh_data(self) -> None:
        """Re-fetch data from DB and recompose the view.

        `@once_per_tick`: multiple synchronous calls on the same view
        within a tick coalesce to one execution (React 18 batching
        pattern). Each `_bus_heartbeat` fans out PRICE + POSITION which
        both subscribe here — without coalescing, `recompose()` would
        run twice per heartbeat.
        """
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
        self.refresh(recompose=True)

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
            self.notify(t("event_detail.notify.no_tradable_market"))
            return
        # Trading requires an active monitor — positions on an unmonitored
        # event would drift without price polling / narrator attention,
        # silently rotting until the user toggles monitor back on. Block
        # here with a clear toast rather than letting the modal open.
        monitor = self._detail.get("monitor") if self._detail else None
        if not (monitor and monitor.get("auto_monitor")):
            self.notify(
                t("event_detail.notify.must_enable_monitor"),
                severity="warning",
            )
            return
        from polily.tui.views.trade_dialog import TradeDialog

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
                t("event_detail.notify.cannot_unmonitor", pos_count=pos_count),
                severity="warning",
            )
            return

        from polily.tui.views.monitor_modals import ConfirmUnmonitorModal

        event = self._detail.get("event") if self._detail else None
        event_title = event.title if event else self.event_id

        def _on_dismiss(confirmed: bool | None) -> None:
            if confirmed:
                self.service.toggle_monitor(self.event_id, enable=False)
                self._after_monitor_change("OFF")

        self.app.push_screen(ConfirmUnmonitorModal(event_title), _on_dismiss)

    def _after_monitor_change(self, state: str) -> None:
        """Post-toggle side effects shared by enable + confirmed-disable.
        `state` is either "ON" or "OFF" — left as ASCII (no translation),
        consistent with how status bar tags are typically rendered."""
        self.notify(t("event_detail.notify.monitor_state", state=state))
        with contextlib.suppress(AttributeError):
            self.screen.refresh_sidebar_counts()
        self.post_message(SwitchVersionRequested(self.event_id, self._version_idx))

    def action_switch_version(self) -> None:
        analyses = self._detail.get("analyses", []) if self._detail else []
        if not analyses:
            self.notify(t("event_detail.notify.no_analysis_version"))
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
                self.notify(t("event_detail.notify.cannot_open_browser"), severity="warning")
        else:
            self.notify(t("event_detail.notify.no_link"), severity="warning")
