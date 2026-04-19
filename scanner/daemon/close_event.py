"""Shared 'close an event' routine used by both recheck and poll_job.

Before this module existed, the two close paths did different things:
`recheck._close_event` flipped `event_monitors.auto_monitor=0` and emitted a
notification; `poll_job`'s inline close did neither. That left closed events
with a dangling auto_monitor=1 row and no user notification. One routine
here keeps the paths aligned.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from scanner.core.db import PolilyDB
from scanner.core.monitor_store import upsert_event_monitor
from scanner.notifications import add_notification

logger = logging.getLogger(__name__)


def close_event(event_id: str, title: str, db: PolilyDB, trigger_source: str) -> None:
    """Mark an event closed, disable its monitor, emit a notification.

    Idempotent within one call — safe to invoke on an already-closed event
    (will re-commit closed=1, re-assert auto_monitor=0, and add another
    notification; callers should gate on closed==0 to avoid notification
    spam).
    """
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
        (now, event_id),
    )
    db.conn.commit()

    upsert_event_monitor(event_id, auto_monitor=False, db=db)

    add_notification(
        db,
        title=f"[CLOSED] {title[:40]}",
        body=f"Event closed ({trigger_source})",
        event_id=event_id,
        trigger_source=trigger_source,
        action_result="closed",
    )

    logger.info("Event %s closed (trigger: %s)", event_id, trigger_source)
