"""EventHeader: title + type/deadline/monitor status + movement."""

from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from polily.core.lifecycle import (
    EventState,
    MarketState,
    event_state,
    market_state,
)
from polily.tui.components.movement_sparkline import (
    get_event_movement,
    movement_label_i18n,
)
from polily.tui.i18n import t
from polily.tui.lifecycle_labels import (
    market_state_label_i18n,
    settled_winner_suffix_i18n,
)
from polily.tui.monitor_format import pick_movement_color

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

    Leading phrase (translated via t() at call time):
      TRADING            → format_countdown(end_date)
      PENDING_SETTLEMENT → event_header.lead.nominally_expired
      SETTLING           → event_header.lead.locked
      SETTLED            → '' (no lead; chain's last element is highlighted)
    """
    state = market_state(market, now=now)

    # Leading phrase
    if state == MarketState.TRADING:
        from polily.tui.utils import format_countdown
        lead = format_countdown(market.end_date) if market.end_date else "?"
    elif state == MarketState.PENDING_SETTLEMENT:
        lead = t("event_header.lead.nominally_expired")
    elif state == MarketState.SETTLING:
        lead = t("event_header.lead.locked")
    else:  # SETTLED
        lead = ""

    current_idx = _STATE_INDEX[state]

    parts: list[str] = []
    for i, s in enumerate(_BREADCRUMB_STATES):
        label = market_state_label_i18n(s)
        if s == MarketState.SETTLED and state == MarketState.SETTLED:
            label = f"{label}{settled_winner_suffix_i18n(market)}"

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
    """EventHeader settlement label for multi-market events.

    ACTIVE                   → format_countdown(event.end_date) (current behavior)
    AWAITING_FULL_SETTLEMENT / RESOLVED → translated event-state label
    """
    from polily.tui.lifecycle_labels import event_state_label_i18n

    state = event_state(event, markets, now=now)
    if state in (EventState.RESOLVED, EventState.AWAITING_FULL_SETTLEMENT):
        return event_state_label_i18n(state)
    from polily.tui.utils import format_countdown
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
            yield Static(f"[dim]{t('event_header.not_found')}[/dim]", classes="hdr-title")
            return

        yield Static(f"[bold]{event.title}[/bold]", classes="hdr-title")

        monitor_str = (
            f"[green]{t('event_header.monitor_on')}[/green]"
            if self._monitor and self._monitor.get("auto_monitor")
            else f"[dim]{t('event_header.monitor_off')}[/dim]"
        )
        mtype = event.market_type or "other"

        if len(self._markets) == 1:
            settlement_str = _binary_breadcrumb(self._markets[0])
        else:
            settlement_str = _multi_event_settlement_label(event, self._markets)

        # Movement status
        m, q, label = get_event_movement(self._movements)
        label_str = movement_label_i18n(label)
        color = pick_movement_color(label, m)
        if label == "noise":
            mov_str = f"[{color}]{label_str}[/{color}] [dim]M:{m:.0f} Q:{q:.0f}[/dim]"
        else:
            mov_str = f"[{color}]{label_str}[/{color}] M:{m:.0f} Q:{q:.0f}"

        yield Static(
            f"{mtype} | {t('event_header.settlement')}: {settlement_str} | {monitor_str} | {mov_str}",
            classes="hdr-sub",
        )
