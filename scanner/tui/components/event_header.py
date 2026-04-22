"""EventHeader: title + type/deadline/monitor status + movement."""

from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from scanner.core.lifecycle import (
    EventState,
    MarketState,
    event_state,
    market_state,
    market_state_label,
    settled_winner_suffix,
)
from scanner.tui.components.movement_sparkline import _LABEL_CN, get_event_movement
from scanner.tui.monitor_format import pick_movement_color

_BREADCRUMB_STATES = [
    MarketState.PENDING_SETTLEMENT,
    MarketState.SETTLING,
    MarketState.SETTLED,
]

_STATE_INDEX: dict[MarketState, int] = {
    MarketState.TRADING: -1,
    MarketState.PENDING_SETTLEMENT: 0,
    MarketState.SETTLING: 1,
    MarketState.SETTLED: 2,
}


def _binary_breadcrumb(market, *, now: datetime | None = None) -> str:
    """Build the binary event breadcrumb: leading phrase + progress chain.

    Styling (Rich markup):
      - current state: [b $primary]{label}[/]
      - past state:    [dim]{label} ✓[/]
      - future state:  [dim]{label}[/]

    Because the containing Static has CSS `color: $text-muted`, dim tags
    reinforce the muted look while `$primary bold` pops the current state
    against that muted background.

    Leading phrase:
      TRADING            → format_countdown(end_date)
      PENDING_SETTLEMENT → '名义已过期'
      SETTLING           → '已锁盘'
      SETTLED            → '' (no lead; chain's last element is highlighted)
    """
    state = market_state(market, now=now)

    # Leading phrase
    if state == MarketState.TRADING:
        from scanner.tui.utils import format_countdown
        lead = format_countdown(market.end_date) if market.end_date else "?"
    elif state == MarketState.PENDING_SETTLEMENT:
        lead = "名义已过期"
    elif state == MarketState.SETTLING:
        lead = "已锁盘"
    else:  # SETTLED
        lead = ""

    current_idx = _STATE_INDEX[state]

    parts: list[str] = []
    for i, s in enumerate(_BREADCRUMB_STATES):
        label = market_state_label(s)
        if s == MarketState.SETTLED and state == MarketState.SETTLED:
            label = f"{label}{settled_winner_suffix(market)}"

        if i < current_idx:
            parts.append(f"[dim]{label} ✓[/]")
        elif i == current_idx:
            parts.append(f"[b $primary]{label}[/]")
        else:
            parts.append(f"[dim]{label}[/]")

    chain = " | ".join(parts)
    if lead:
        return f"{lead} | {chain}"
    return chain


def _multi_event_settlement_label(event, markets, *, now: datetime | None = None) -> str:
    """EventHeader '结算:' label for multi-market events.

    ACTIVE                   → format_countdown(event.end_date) (current behavior)
    AWAITING_FULL_SETTLEMENT → '待全部结算'
    RESOLVED                 → '已结算'
    """
    state = event_state(event, markets, now=now)
    if state == EventState.RESOLVED:
        return "已结算"
    if state == EventState.AWAITING_FULL_SETTLEMENT:
        return "待全部结算"
    from scanner.tui.utils import format_countdown
    return format_countdown(event.end_date) if event.end_date else "?"


class EventHeader(Widget):
    """Event title bar with type, deadline, monitor status, and movement."""

    DEFAULT_CSS = """
    EventHeader { height: auto; }
    EventHeader .hdr-title { text-style: bold; color: $primary; padding: 1 0 0 1; }
    /* v0.8.0: add vertical breathing room so meta row separates from title above + KPI row below. */
    EventHeader .hdr-sub { color: $text-muted; padding: 1 0 1 2; }
    """

    def __init__(
        self,
        event,
        monitor: dict | None = None,
        movements: list | None = None,
        markets: list | None = None,
    ):
        super().__init__()
        self._event = event
        self._monitor = monitor
        self._movements = movements or []
        self._markets = markets or []

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
        mtype = event.market_type or "other"

        if len(self._markets) == 1:
            settlement_str = _binary_breadcrumb(self._markets[0])
        else:
            settlement_str = _multi_event_settlement_label(event, self._markets)

        # Movement status (unchanged)
        m, q, label = get_event_movement(self._movements)
        label_cn = _LABEL_CN.get(label, label)
        color = pick_movement_color(label, m)
        if label == "noise":
            mov_str = f"[{color}]{label_cn}[/{color}] [dim]M:{m:.0f} Q:{q:.0f}[/dim]"
        else:
            mov_str = f"[{color}]{label_cn}[/{color}] M:{m:.0f} Q:{q:.0f}"

        yield Static(
            f"{mtype} | 结算: {settlement_str} | {monitor_str} | {mov_str}",
            classes="hdr-sub",
        )
