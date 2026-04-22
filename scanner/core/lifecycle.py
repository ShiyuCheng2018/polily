"""Market / Event lifecycle state derivation.

States are derived (not stored). Four market states + three event states
cover the full lifecycle from Gamma listing → Polymarket UMA resolution →
Polily wallet credit.

See docs/internal/plans/2026-04-22-v085-market-event-lifecycle-design.md
for the state machine and trigger conditions.

POC 2026-04-22: Polymarket's Gamma API flips `closed` and `acceptingOrders`
together — there is no intermediate state where `closed=false AND
acceptingOrders=false`. So SETTLING is driven by `markets.closed=1 AND
resolved_outcome IS NULL` (UMA 2h challenge window), not by a new
`acceptingOrders` poll.
"""

from __future__ import annotations

from enum import Enum


class MarketState(Enum):
    TRADING = "trading"
    PENDING_SETTLEMENT = "pending_settlement"
    SETTLING = "settling"
    SETTLED = "settled"


class EventState(Enum):
    ACTIVE = "active"
    AWAITING_FULL_SETTLEMENT = "awaiting_full_settlement"
    RESOLVED = "resolved"


_MARKET_LABELS_CN: dict[MarketState, str] = {
    MarketState.TRADING: "交易中",
    MarketState.PENDING_SETTLEMENT: "即将结算",
    MarketState.SETTLING: "结算中",
    MarketState.SETTLED: "已结算",
}

_EVENT_LABELS_CN: dict[EventState, str] = {
    EventState.ACTIVE: "进行中",
    EventState.AWAITING_FULL_SETTLEMENT: "待全部结算",
    EventState.RESOLVED: "已结算",
}


def market_state_label(state: MarketState) -> str:
    """Chinese user-facing label for a market state."""
    return _MARKET_LABELS_CN[state]


def event_state_label(state: EventState) -> str:
    """Chinese user-facing label for an event state."""
    return _EVENT_LABELS_CN[state]


def settled_winner_suffix(market) -> str:
    """Render ' YES 获胜' / ' NO 获胜' / ' 平局' / '' from resolved_outcome.

    Single source of truth; called from both event_header breadcrumb and
    event_detail zone title.

    resolved_outcome=None → '' (caller shows plain '已结算' label).
    """
    outcome = getattr(market, "resolved_outcome", None)
    if outcome == "yes":
        return " YES 获胜"
    if outcome == "no":
        return " NO 获胜"
    if outcome == "split":
        return " 平局"
    return ""
