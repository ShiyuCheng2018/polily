"""Event monitor persistence — controls the intelligence layer."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB


def upsert_event_monitor(
    event_id: str,
    *,
    auto_monitor: bool,
    price_snapshot: str | None = None,
    notes: str | None = None,
    db: PolilyDB,
) -> None:
    """Insert or update event monitor. Preserves next_check_at on update."""
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        """
        INSERT INTO event_monitors (event_id, auto_monitor, price_snapshot, notes, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            auto_monitor=excluded.auto_monitor,
            price_snapshot=COALESCE(excluded.price_snapshot, event_monitors.price_snapshot),
            notes=COALESCE(excluded.notes, event_monitors.notes),
            updated_at=excluded.updated_at
        """,
        (event_id, 1 if auto_monitor else 0, price_snapshot, notes, now),
    )
    db.conn.commit()


def get_event_monitor(event_id: str, db: PolilyDB) -> dict | None:
    """Get monitor state for an event. Returns dict or None."""
    row = db.conn.execute(
        "SELECT * FROM event_monitors WHERE event_id = ?", (event_id,)
    ).fetchone()
    return dict(row) if row else None


def get_active_monitors(db: PolilyDB) -> list[str]:
    """Get event_ids with auto_monitor=1."""
    rows = db.conn.execute(
        "SELECT event_id FROM event_monitors WHERE auto_monitor = 1"
    ).fetchall()
    return [r["event_id"] for r in rows]


def update_next_check_at(
    event_id: str,
    next_check_at: str | None,
    reason: str | None,
    db: PolilyDB,
) -> None:
    """Update the next AI check time for an event.

    Uses UPSERT: if no event_monitors row exists, creates one with
    auto_monitor=0 (stores schedule without enabling monitoring).
    """
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        """
        INSERT INTO event_monitors (event_id, auto_monitor, next_check_at, next_check_reason, updated_at)
        VALUES (?, 0, ?, ?, ?)
        ON CONFLICT(event_id) DO UPDATE SET
            next_check_at=excluded.next_check_at,
            next_check_reason=excluded.next_check_reason,
            updated_at=excluded.updated_at
        """,
        (event_id, next_check_at, reason, now),
    )
    db.conn.commit()

    # Notify daemon to reload check jobs from DB
    if next_check_at:
        from scanner.daemon.notify import notify_daemon
        notify_daemon()
