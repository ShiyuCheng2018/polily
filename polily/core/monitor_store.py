"""Event monitor persistence — controls the intelligence layer."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polily.core.db import PolilyDB


def upsert_event_monitor(
    event_id: str,
    *,
    auto_monitor: bool,
    price_snapshot: str | None = None,
    notes: str | None = None,
    db: PolilyDB,
) -> None:
    """Insert or update event monitor."""
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
