"""Watch recheck orchestration: analyze_market + state transition + notification."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from scanner.market_state import MarketState, get_market_state, set_market_state
from scanner.notifications import add_notification, send_desktop_notification

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
    """Full recheck: validate → analyze → transition → notify.

    Args:
        market_id: Market to recheck.
        db: PolilyDB instance.
        service: ScanService instance. If None, only checks expiry (for unit tests).
        trigger_source: 'manual' / 'scheduled'
    """
    state = get_market_state(market_id, db)
    if state is None:
        raise ValueError(f"Market {market_id} not found in market_states")

    # Check expiry
    if state.resolution_time:
        try:
            res_time = datetime.fromisoformat(state.resolution_time)
            if res_time < datetime.now(UTC):
                return _close_market(market_id, state, db)
        except ValueError:
            logger.warning("Invalid resolution_time for %s: %s", market_id, state.resolution_time)

    # Without service, just return current status (unit test mode)
    if service is None:
        return RecheckResult(
            market_id=market_id,
            new_status=state.status,
            previous_price=state.price_at_watch,
            watch_sequence=state.watch_sequence,
        )

    # Full AI analysis — same path as TUI
    import asyncio
    version = asyncio.run(
        service.analyze_market(market_id, trigger_source=trigger_source),
    )

    # Read AI output action
    narrative = version.narrative_output
    action = narrative.get("action", "PASS") if isinstance(narrative, dict) else "PASS"

    # Map AI action → DB status
    status_map = {"BUY_YES": "buy_yes", "BUY_NO": "buy_no", "WATCH": "watch", "PASS": "pass"}
    new_status = status_map.get(action, "pass")

    current_price = version.yes_price_at_analysis
    previous_price = state.price_at_watch

    # State transition
    if new_status == "watch":
        watch_data = narrative.get("watch", {}) if isinstance(narrative, dict) else {}
        state.status = "watch"
        state.watch_sequence = state.watch_sequence + 1
        state.next_check_at = watch_data.get("next_check_at")
        state.watch_reason = watch_data.get("reason")
        state.price_at_watch = current_price
        state.wc_watch_reason = watch_data.get("watch_reason", "")
        state.wc_better_entry = watch_data.get("better_entry", "")
        state.wc_trigger_event = watch_data.get("trigger_event", "")
        state.wc_invalidation = watch_data.get("invalidation", "")
    else:
        state.status = new_status
        state.next_check_at = None
        state.watch_reason = None
        state.auto_monitor = False

    state.updated_at = datetime.now(UTC).isoformat()
    set_market_state(market_id, state, db)

    _notify(db, market_id, state.title, new_status, previous_price, current_price, trigger_source)

    return RecheckResult(
        market_id=market_id,
        new_status=new_status,
        previous_price=previous_price,
        current_price=current_price,
        watch_sequence=state.watch_sequence,
        next_check_at=state.next_check_at,
        reason=state.watch_reason,
    )


def _close_market(market_id: str, state: MarketState, db) -> RecheckResult:
    """Transition a market to closed status."""
    state.status = "closed"
    state.updated_at = datetime.now(UTC).isoformat()
    state.auto_monitor = False
    state.next_check_at = None
    set_market_state(market_id, state, db)

    _notify(db, market_id, state.title, "closed", state.price_at_watch, None, "system")

    return RecheckResult(
        market_id=market_id,
        new_status="closed",
        previous_price=state.price_at_watch,
        watch_sequence=state.watch_sequence,
    )


def _notify(db, market_id, title, new_status, old_price, new_price, trigger_source):
    """Send desktop notification + persist to DB."""
    price_str = ""
    if old_price is not None and new_price is not None and old_price > 0:
        delta = (new_price - old_price) / old_price * 100
        price_str = f"YES {old_price:.2f} -> {new_price:.2f} ({delta:+.1f}%)"

    labels = {
        "buy_yes": "GO BUY YES", "buy_no": "GO BUY NO",
        "watch": "WATCH", "pass": "PASS", "closed": "CLOSED",
    }
    label = labels.get(new_status, new_status.upper())
    title_short = (title or "")[:40]

    notif_title = f"[{label}] {title_short}"
    notif_body = price_str or f"Status: {label}"

    add_notification(
        db, title=notif_title, body=notif_body,
        market_id=market_id, trigger_source=trigger_source,
        action_result=new_status,
    )
    send_desktop_notification(notif_title, notif_body)
