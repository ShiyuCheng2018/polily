"""Event-level recheck: expiry detection + AI analysis trigger."""
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from scanner.core.db import PolilyDB
from scanner.core.event_store import get_event, get_event_markets

logger = logging.getLogger(__name__)


@dataclass
class RecheckResult:
    event_id: str
    closed: bool = False
    next_check_at: str | None = None
    trigger_source: str = "manual"


def recheck_event(
    event_id: str,
    *,
    db: PolilyDB,
    service=None,
    trigger_source: str = "manual",
) -> RecheckResult:
    """Full recheck: validate → [analyze] → close/notify.

    Three-layer expiry detection:
    1. events.end_date past → close
    2. All sub-markets closed → close
    3. (404 detection is in poll_job, not here)

    When service is None (test mode), only expiry checks run.
    """
    event = get_event(event_id, db)
    if event is None:
        raise ValueError(f"Event {event_id} not found")

    # Layer 1: Check end_date expiry
    if event.end_date:
        try:
            end = datetime.fromisoformat(event.end_date.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            if end < datetime.now(UTC):
                return _close_event(event_id, event.title, db, trigger_source)
        except ValueError:
            logger.warning("Invalid end_date for %s: %s", event_id, event.end_date)

    # Layer 2: Check if all sub-markets closed
    markets = get_event_markets(event_id, db)
    if markets and all(m.closed for m in markets):
        return _close_event(event_id, event.title, db, trigger_source)

    # AI analysis (only when service provided)
    if service is not None:
        try:
            import asyncio

            version = asyncio.run(
                service.analyze_event(event_id, trigger_source=trigger_source)
            )
            # Update check schedule from AI output
            if hasattr(version, "narrative_output") and isinstance(
                version.narrative_output, dict
            ):
                next_check = version.narrative_output.get("next_check_at")
                if next_check:
                    from scanner.core.monitor_store import update_next_check_at

                    reason = version.narrative_output.get("next_check_reason", "")
                    update_next_check_at(event_id, next_check, reason, db, notify=False)
                    return RecheckResult(
                        event_id=event_id,
                        next_check_at=next_check,
                        trigger_source=trigger_source,
                    )
        except Exception:
            logger.exception("AI analysis failed for %s", event_id)

    return RecheckResult(event_id=event_id, trigger_source=trigger_source)


def _close_event(
    event_id: str, title: str, db: PolilyDB, trigger_source: str
) -> RecheckResult:
    """Mark event as closed + notify."""
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
        (now, event_id),
    )
    db.conn.commit()

    # Disable monitoring for closed event
    from scanner.core.monitor_store import upsert_event_monitor

    upsert_event_monitor(event_id, auto_monitor=False, db=db)

    # Send notification
    from scanner.notifications import add_notification

    add_notification(
        db,
        title=f"[CLOSED] {title[:40]}",
        body=f"Event closed ({trigger_source})",
        event_id=event_id,
        trigger_source=trigger_source,
        action_result="closed",
    )

    logger.info("Event %s closed (trigger: %s)", event_id, trigger_source)
    return RecheckResult(event_id=event_id, closed=True, trigger_source=trigger_source)
