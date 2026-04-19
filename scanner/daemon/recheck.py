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

    # Already-closed events no-op out. Needed because auto_monitor stays 1
    # through close (it's a user-intent flag) so the scheduler may still
    # invoke recheck_event here; without this gate Layer 2 would re-enter
    # close_event and fire a duplicate [CLOSED] notification.
    if event.closed == 1:
        logger.debug("Skipping recheck for already-closed event %s", event_id)
        return RecheckResult(event_id=event_id, trigger_source=trigger_source)

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
                    from scanner.scan_log import (
                        insert_pending_scan,
                        supersede_pending_for_event,
                    )

                    supersede_pending_for_event(event_id, db)
                    insert_pending_scan(
                        event_id=event_id,
                        event_title=event.title,
                        scheduled_at=next_check,
                        trigger_source="scheduled",
                        scheduled_reason=version.narrative_output.get(
                            "next_check_reason", ""
                        ),
                        db=db,
                    )
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
    """Mark event as closed + notify via the shared close routine."""
    from scanner.daemon.close_event import close_event

    close_event(event_id, title, db, trigger_source)
    return RecheckResult(event_id=event_id, closed=True, trigger_source=trigger_source)
