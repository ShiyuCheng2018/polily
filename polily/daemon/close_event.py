"""Shared 'close an event' routine invoked from the poll_job close path.

`auto_monitor` is intentionally not touched — it's a user-intent flag
("did the user choose to monitor this event") whose value at the moment of
close is load-bearing for the Archive view ("list the events I was
monitoring when they closed"). Callers must gate on `event.closed == 0`
themselves to avoid firing duplicate close side-effects.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from polily.core.db import PolilyDB

logger = logging.getLogger(__name__)


def close_event(event_id: str, title: str, db: PolilyDB, trigger_source: str) -> None:
    """Mark an event closed. Preserves auto_monitor."""
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
        (now, event_id),
    )
    db.conn.commit()

    logger.info(
        "Event %s closed (title=%r, trigger=%s)",
        event_id, title[:40], trigger_source,
    )
