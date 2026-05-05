"""TUI-side i18n wrappers around polily.core.lifecycle label functions.

`core/lifecycle.py` is intentionally framework-free and its label helpers
(market_state_label / event_state_label / settled_winner_suffix) return
Chinese-only strings. This module wraps them so every TUI consumer
(event_detail, event_header, sub_market_table, score_result, event_kpi)
flips on language switch via t(), without dragging the i18n module into
core/.

Usage:
    from polily.tui.lifecycle_labels import (
        market_state_label_i18n,
        event_state_label_i18n,
        settled_winner_suffix_i18n,
    )

    label = market_state_label_i18n(market_state(market))
"""
from __future__ import annotations

from polily.core.lifecycle import EventState, MarketState
from polily.tui.i18n import t

_MARKET_KEY = {
    MarketState.TRADING: "lifecycle.market.trading",
    MarketState.PENDING_SETTLEMENT: "lifecycle.market.pending_settlement",
    MarketState.SETTLING: "lifecycle.market.settling",
    MarketState.SETTLED: "lifecycle.market.settled",
}

_EVENT_KEY = {
    EventState.ACTIVE: "lifecycle.event.active",
    EventState.AWAITING_FULL_SETTLEMENT: "lifecycle.event.awaiting_full_settlement",
    EventState.RESOLVED: "lifecycle.event.resolved",
}

_OUTCOME_KEY = {
    "yes": "lifecycle.outcome.yes_won",
    "no": "lifecycle.outcome.no_won",
    "split": "lifecycle.outcome.split",
    "void": "lifecycle.outcome.void",
}


def market_state_label_i18n(state: MarketState) -> str:
    return t(_MARKET_KEY[state])


def event_state_label_i18n(state: EventState) -> str:
    return t(_EVENT_KEY[state])


def settled_winner_suffix_i18n(market) -> str:
    """Localized outcome suffix appended to a SETTLED market's state label.

    Mirrors core.lifecycle.settled_winner_suffix's contract: returns a
    leading-space-prefixed string (' YES won' / ' NO won' / ' Split' /
    ' Void') so callers can concatenate unconditionally. Empty string
    when resolved_outcome is None or unrecognized.
    """
    outcome = getattr(market, "resolved_outcome", None)
    if not outcome or not isinstance(outcome, str):
        return ""
    key = _OUTCOME_KEY.get(outcome)
    return f" {t(key)}" if key else ""
