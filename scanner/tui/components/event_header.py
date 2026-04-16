"""EventHeader: title + type/deadline/monitor status + movement."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from scanner.tui.components.movement_sparkline import _LABEL_CN, get_event_movement


class EventHeader(Widget):
    """Event title bar with type, deadline, monitor status, and movement."""

    DEFAULT_CSS = """
    EventHeader { height: auto; }
    EventHeader .hdr-title { text-style: bold; color: $primary; padding: 1 0 0 1; }
    EventHeader .hdr-sub { color: $text-muted; padding: 0 0 0 2; }
    """

    def __init__(self, event, monitor: dict | None = None, movements: list | None = None):
        super().__init__()
        self._event = event
        self._monitor = monitor
        self._movements = movements or []

    def compose(self) -> ComposeResult:
        event = self._event
        if not event:
            yield Static("[dim]事件未找到[/dim]", classes="hdr-title")
            return

        yield Static(f"[bold]{event.title}[/bold]", classes="hdr-title")

        monitor_str = (
            "[green]监控 ON[/green]"
            if self._monitor and self._monitor.get("auto_monitor")
            else "[dim]监控 OFF[/dim]"
        )
        deadline_str = "?"
        if event.end_date:
            from scanner.tui.utils import format_countdown
            deadline_str = format_countdown(event.end_date)
        mtype = event.market_type or "other"

        # Movement status
        m, q, label = get_event_movement(self._movements)
        label_cn = _LABEL_CN.get(label, label)
        if label == "noise":
            mov_str = f"[green]{label_cn}[/green] [dim]M:{m:.0f} Q:{q:.0f}[/dim]"
        else:
            color = "red" if m >= 70 else "yellow"
            mov_str = f"[{color}]{label_cn}[/] M:{m:.0f} Q:{q:.0f}"

        yield Static(
            f"{mtype} | 结算: {deadline_str} | {monitor_str} | {mov_str}",
            classes="hdr-sub",
        )
