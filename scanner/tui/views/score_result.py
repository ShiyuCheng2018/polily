"""ScoreResultView: scoring result page — steps + event detail + action buttons.

v0.8.0 migration:
- PolilyZone atoms wrap 评分步骤 / 事件信息 / 市场 sections.
- ICON_SCAN / ICON_EVENT / ICON_MARKET from the atom icon set.
- NAV_BINDINGS for list-nav keys (step list is scroll-heavy); `escape`
  / `backspace` kept for go-back.
- VerticalScroll + zone height constraints so the action bar at the
  bottom (重新评分 / 添加到监控) stays visible on short terminals.
- Static snapshot view — no EventBus subscription (the outer screen
  owns rescore/refresh wiring). Users re-trigger via 重新评分.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

from scanner.scan_log import ScanLogEntry
from scanner.tui.bindings import NAV_BINDINGS
from scanner.tui.components import (
    BinaryMarketStructurePanel,
    EventHeader,
    EventKpiRow,
    SubMarketTable,
)
from scanner.tui.icons import ICON_EVENT, ICON_MARKET, ICON_SCAN
from scanner.tui.service import ScanService
from scanner.tui.widgets.polily_zone import PolilyZone


class BackToTasks(Message):
    pass


class ScoreViewRescore(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class AddToMonitorRequested(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class ScoreResultView(Widget):
    """Scoring result: steps + event detail components + action buttons."""

    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("backspace", "go_back", show=False),
        Binding("enter", "open_event", "打开事件", show=True),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    ScoreResultView { height: 1fr; }
    ScoreResultView > VerticalScroll { height: 1fr; }
    ScoreResultView > VerticalScroll > PolilyZone { height: auto; }
    ScoreResultView .step-row { padding: 0 0 0 2; }
    ScoreResultView #action-bar { height: auto; dock: bottom; padding: 1 1; }
    ScoreResultView #action-row { height: 3; }
    ScoreResultView #action-row Button { margin: 0 1; }
    """

    def __init__(self, event_id: str, service: ScanService):
        super().__init__()
        self.event_id = event_id
        self.service = service

    def compose(self) -> ComposeResult:
        log = self._get_log_entry()
        detail = self.service.get_event_detail(self.event_id)
        event = detail["event"] if detail else None
        markets = detail.get("markets", []) if detail else []
        monitor = detail.get("monitor") if detail else None
        is_expired = self._is_expired(event)
        is_monitored = self._is_monitored()

        with VerticalScroll(id="scroll-area"):
            # Zone: 评分步骤 (only when a scan log is found)
            if log and log.steps:
                with PolilyZone(title=f"{ICON_SCAN} 评分步骤", id="steps-zone"):
                    for step in log.steps:
                        elapsed_str = f"[dim]{step.elapsed:.1f}s[/dim]"
                        detail_text = (
                            f"  [cyan]{step.detail}[/cyan]" if step.detail else ""
                        )
                        status_label = {
                            "done": "[green]done[/green]",
                            "skip": "[dim]skip[/dim]",
                            "fail": "[red]FAIL[/red]",
                        }.get(step.status, step.status)
                        yield Static(
                            f"  {status_label}  {step.name}"
                            f"{detail_text}     {elapsed_str}",
                            classes="step-row",
                        )

            # Zone: 事件信息 (header + KPI row)
            with PolilyZone(title=f"{ICON_EVENT} 事件信息", id="event-info-zone"):
                yield EventHeader(event, monitor)
                yield EventKpiRow(event, markets)

            # Zone: 市场 — binary events show the structure panel (same as
            # EventDetailView); multi-outcome events use SubMarketTable.
            with PolilyZone(title=f"{ICON_MARKET} 市场", id="market-zone"):
                if len(markets) == 1:
                    yield BinaryMarketStructurePanel(markets[0], event)
                else:
                    yield SubMarketTable(markets, event)

        # Action bar stays outside the scroll so it's always reachable.
        with Vertical(id="action-bar"):
            if is_expired:
                yield Static(
                    "  事件已过期",
                    classes="expired-msg text-error p-sm",
                )
            else:
                with Horizontal(id="action-row"):
                    yield Button("重新评分", id="rescore-btn", variant="default")
                    if not is_monitored:
                        yield Button(
                            "添加到监控", id="monitor-btn", variant="primary",
                        )
                    else:
                        yield Static("  [dim]已在监控列表[/dim]")

    def _get_log_entry(self) -> ScanLogEntry | None:
        logs = self.service.get_scan_logs()
        for log in logs:
            if log.type == "add_event" and log.event_id == self.event_id:
                return log
        return None

    def _is_expired(self, event) -> bool:
        if not event or not event.end_date:
            return False
        from datetime import UTC, datetime
        try:
            end = datetime.fromisoformat(event.end_date.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            return end < datetime.now(UTC)
        except (ValueError, TypeError):
            return False

    def _is_monitored(self) -> bool:
        return self.service.is_event_monitored(self.event_id)

    def on_button_pressed(self, event) -> None:
        if not hasattr(event, "button"):
            return
        if event.button.id == "rescore-btn":
            self.post_message(ScoreViewRescore(self.event_id))
        elif event.button.id == "monitor-btn":
            self.post_message(AddToMonitorRequested(self.event_id))

    def action_go_back(self) -> None:
        self.post_message(BackToTasks())

    def action_open_event(self) -> None:
        """Enter → open EventDetailView for this scored event."""
        from scanner.tui.views.scan_log import OpenEventFromLog
        self.post_message(OpenEventFromLog(self.event_id))
