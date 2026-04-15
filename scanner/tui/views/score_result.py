"""ScoreResultView: scoring result page — steps + full event detail + action buttons."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

from scanner.scan_log import ScanLogEntry
from scanner.tui.service import ScanService
from scanner.tui.views.market_detail import MarketDetailView


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
    """Scoring result: steps + full event detail (via MarketDetailView) + action buttons."""

    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("backspace", "go_back", show=False),
    ]

    DEFAULT_CSS = """
    ScoreResultView { height: 1fr; }
    ScoreResultView #steps-section { height: auto; padding: 0 1; }
    ScoreResultView .section-title { text-style: bold; color: $primary; padding: 1 0 0 0; }
    ScoreResultView .step-row { padding: 0 0 0 2; }
    ScoreResultView #detail-section { height: 1fr; }
    ScoreResultView #action-section { height: auto; padding: 1 1; }
    ScoreResultView #action-row { height: 3; }
    ScoreResultView #action-row Button { margin: 0 1; }
    ScoreResultView .expired-msg { color: $error; padding: 1 2; }
    """

    def __init__(self, event_id: str, service: ScanService):
        super().__init__()
        self.event_id = event_id
        self.service = service

    def compose(self) -> ComposeResult:
        log = self._get_log_entry()
        detail = self.service.get_event_detail(self.event_id)
        event = detail["event"] if detail else None
        is_expired = self._is_expired(event)
        is_monitored = self._is_monitored()

        # --- Steps ---
        with Vertical(id="steps-section"):
            if log and log.steps:
                yield Static(" 评分步骤", classes="section-title")
                for step in log.steps:
                    elapsed_str = f"[dim]{step.elapsed:.1f}s[/dim]"
                    detail_text = f"  [cyan]{step.detail}[/cyan]" if step.detail else ""
                    status_label = {
                        "done": "[green]done[/green]",
                        "skip": "[dim]skip[/dim]",
                        "fail": "[red]FAIL[/red]",
                    }.get(step.status, step.status)
                    yield Static(f"  {status_label}  {step.name}{detail_text}     {elapsed_str}", classes="step-row")

        # --- Full event detail (reuse MarketDetailView) ---
        with Vertical(id="detail-section"):
            yield MarketDetailView(
                event_id=self.event_id, service=self.service,
            )

        # --- Action buttons ---
        with Vertical(id="action-section"):
            if is_expired:
                yield Static("  事件已过期", classes="expired-msg")
            else:
                with Horizontal(id="action-row"):
                    yield Button("重新评分", id="rescore-btn", variant="default")
                    if not is_monitored:
                        yield Button("添加到监控", id="monitor-btn", variant="primary")
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
        from scanner.core.monitor_store import get_event_monitor
        mon = get_event_monitor(self.event_id, self.service.db)
        return bool(mon and mon.get("auto_monitor"))

    def on_button_pressed(self, event) -> None:
        if not hasattr(event, "button"):
            return
        if event.button.id == "rescore-btn":
            self.post_message(ScoreViewRescore(self.event_id))
        elif event.button.id == "monitor-btn":
            self.post_message(AddToMonitorRequested(self.event_id))

    def action_go_back(self) -> None:
        self.post_message(BackToTasks())
