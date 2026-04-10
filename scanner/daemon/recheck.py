"""Watch recheck orchestration: analyze_market + state transition + notification.

TODO: v0.5.0 — rewrite against event-first schema (event_monitors + events tables).
Currently stubbed: market_states table was removed.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RecheckResult:
    market_id: str
    new_status: str  # buy_yes, buy_no, watch, pass, closed
    previous_price: float | None = None
    current_price: float | None = None
    watch_sequence: int = 0
    next_check_at: str | None = None
    reason: str | None = None


def recheck_market(
    market_id: str,
    *,
    db,
    service=None,
    trigger_source: str = "manual",
) -> RecheckResult:
    """Full recheck: validate -> analyze -> transition -> notify.

    TODO: v0.5.0 — rewrite to use event_monitors instead of market_states.
    """
    raise NotImplementedError(
        "v0.5.0 TODO: recheck_market needs rewrite for event-first schema"
    )


def _close_market(market_id: str, state, db) -> RecheckResult:
    """Transition a market to closed status.

    TODO: v0.5.0 — rewrite to use event_monitors.
    """
    raise NotImplementedError(
        "v0.5.0 TODO: _close_market needs rewrite for event-first schema"
    )
