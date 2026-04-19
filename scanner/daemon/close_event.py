"""Shared 'close an event' routine used by both recheck and poll_job.

Unifies two closure paths that previously diverged: recheck emitted a
notification on close, poll didn't. Now both go through `close_event()`.

`auto_monitor` is intentionally **not** touched — it's a user-intent flag
("did the user choose to monitor this event") whose value at the moment of
close is load-bearing for the Archive view ("list the events I was
monitoring when they closed"). Callers that need to stop the scheduler from
re-invoking this routine on already-closed events must gate on
`event.closed == 0` themselves (see `recheck_event` and the closure branch
of `poll_job`).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from scanner.core.db import PolilyDB
from scanner.notifications import add_notification

logger = logging.getLogger(__name__)


def close_event(event_id: str, title: str, db: PolilyDB, trigger_source: str) -> None:
    """Mark an event closed and emit a notification. Preserves auto_monitor."""
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
        (now, event_id),
    )
    db.conn.commit()

    add_notification(
        db,
        title=f"[CLOSED] {title[:40]}",
        body=f"Event closed ({trigger_source})",
        event_id=event_id,
        trigger_source=trigger_source,
        action_result="closed",
    )

    logger.info("Event %s closed (trigger: %s)", event_id, trigger_source)
