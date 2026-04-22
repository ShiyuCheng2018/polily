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

from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.event_store import MarketRow


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


def settled_winner_suffix(market: MarketRow) -> str:
    """Render ' YES 获胜' / ' NO 获胜' / ' 平局' / ' 市场作废' / '' from resolved_outcome.

    Single source of truth; called from both event_header breadcrumb and
    event_detail zone title.

    Note: the non-empty returns include a leading space so callers can
    concatenate unconditionally: `f"{label}{settled_winner_suffix(m)}"`.
    Do NOT add a space at the call site.

    resolved_outcome=None → '' (caller shows plain '已结算' label).
    """
    outcome = market.resolved_outcome
    if outcome == "yes":
        return " YES 获胜"
    if outcome == "no":
        return " NO 获胜"
    if outcome == "split":
        return " 平局"
    if outcome == "void":
        return " 市场作废"
    return ""


def market_state(market, *, now: datetime | None = None) -> MarketState:
    """Derive the current lifecycle state of a market.

    Priority (terminal states checked first):
      1. closed=1 AND resolved_outcome IS NOT NULL → SETTLED
      2. closed=1 AND resolved_outcome IS NULL     → SETTLING (UMA window)
      3. closed=0 AND (end_date IS NULL OR end_date > now) → TRADING
      4. closed=0 AND end_date ≤ now               → PENDING_SETTLEMENT

    `now` is injectable for testability; defaults to datetime.now(UTC).

    NULL end_date with closed=0 → TRADING (a pre-scheduled market that
    hasn't been given a deadline yet is active, not pending).
    """
    closed = int(market.closed or 0)
    if closed == 1:
        if market.resolved_outcome is None:
            return MarketState.SETTLING
        return MarketState.SETTLED

    # closed=0 from here on
    if market.end_date is None:
        return MarketState.TRADING

    if now is None:
        now = datetime.now(UTC)

    try:
        end = datetime.fromisoformat(market.end_date)
    except (ValueError, TypeError):
        # Malformed end_date (corrupt row / Gamma schema drift).
        # Safer to treat as TRADING than classify as PENDING_SETTLEMENT
        # when we can't even parse the date.
        return MarketState.TRADING

    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    if end <= now:
        return MarketState.PENDING_SETTLEMENT
    return MarketState.TRADING


def event_state(
    event, markets: list, *, now: datetime | None = None,
) -> EventState:
    """Derive the event lifecycle state from child markets.

    Priority:
      1. event.closed=1 → RESOLVED (terminal)
      2. any child market in TRADING → ACTIVE
      3. otherwise → AWAITING_FULL_SETTLEMENT

    Empty markets list on an open event → ACTIVE (pre-scoring edge case).
    """
    if int(event.closed or 0) == 1:
        return EventState.RESOLVED

    if not markets:
        return EventState.ACTIVE

    for m in markets:
        if market_state(m, now=now) == MarketState.TRADING:
            return EventState.ACTIVE

    return EventState.AWAITING_FULL_SETTLEMENT
