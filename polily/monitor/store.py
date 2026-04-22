"""Persist and query movement detection results (event-level)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polily.core.db import PolilyDB


def append_movement(
    *,
    event_id: str,
    market_id: str | None = None,
    yes_price: float | None = None,
    no_price: float | None = None,
    prev_yes_price: float | None = None,
    trade_volume: float = 0.0,
    bid_depth: float = 0.0,
    ask_depth: float = 0.0,
    spread: float | None = None,
    magnitude: float = 0.0,
    quality: float = 0.0,
    label: str = "noise",
    triggered_analysis: bool = False,
    snapshot: str = "{}",
    db: PolilyDB,
) -> None:
    """Append a movement log entry."""

    db.conn.execute(
        """INSERT INTO movement_log
        (event_id, market_id, created_at, yes_price, no_price, prev_yes_price,
         trade_volume, bid_depth, ask_depth, spread,
         magnitude, quality, label, triggered_analysis, snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id,
            market_id,
            datetime.now(UTC).isoformat(),
            yes_price,
            no_price,
            prev_yes_price,
            trade_volume,
            bid_depth,
            ask_depth,
            spread,
            magnitude,
            quality,
            label,
            1 if triggered_analysis else 0,
            snapshot,
        ),
    )
    # Note: caller is responsible for commit (batch commit in poll_job)


def get_event_movements(event_id: str, db: PolilyDB, hours: int = 6) -> list[dict]:
    """Get all movement log entries for an event within the last N hours.

    Returns both sub-market entries and event-level aggregate entries,
    ordered by created_at DESC (most recent first).
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    rows = db.conn.execute(
        """SELECT * FROM movement_log
        WHERE event_id = ? AND created_at >= ?
        ORDER BY created_at DESC""",
        (event_id, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def get_event_latest(event_id: str, db: PolilyDB) -> dict | None:
    """Get the most recent movement_log entry for an event."""
    row = db.conn.execute(
        """SELECT * FROM movement_log
        WHERE event_id = ?
        ORDER BY id DESC LIMIT 1""",
        (event_id,),
    ).fetchone()
    return dict(row) if row else None


def get_today_analysis_count(event_id: str, db: PolilyDB) -> int:
    """Count how many times an event triggered AI analysis today."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    row = db.conn.execute(
        """SELECT COUNT(*) FROM movement_log
        WHERE event_id = ? AND triggered_analysis = 1
        AND created_at >= ?""",
        (event_id, today),
    ).fetchone()
    return row[0] if row else 0


def get_movement_summary(event_id: str, db: PolilyDB, hours: int = 6) -> str | None:
    """Build a human-readable movement summary for AI context.

    Includes all sub-market entries and event-level aggregates.
    Returns None if no movements in the window.
    """
    entries = get_event_movements(event_id, db, hours=hours)
    if not entries:
        return None

    parts = [f"--- Movement Log (last {hours}h, {len(entries)} entries) ---"]
    for e in reversed(entries):  # chronological order
        ts = e["created_at"][:16]  # trim to minute
        market = e.get("market_id") or "event"
        price = e.get("yes_price", "?")
        prev = e.get("prev_yes_price", "?")
        mag = e["magnitude"]
        qual = e["quality"]
        label = e["label"]
        triggered = " [TRIGGERED AI]" if e.get("triggered_analysis") else ""
        parts.append(
            f"  {ts} [{market}]: {prev} → {price} | M={mag:.0f} Q={qual:.0f} [{label}]{triggered}"
        )

    return "\n".join(parts)


# --- Backward-compatible aliases (used by poll.py and daemon/poll_job.py) ---
# These will be removed when poll.py is rewritten for event-first schema.


def get_recent_movements(market_id: str, db: PolilyDB, hours: int = 6) -> list[dict]:
    """Get recent movement_log entries by market_id.

    Backward-compatible alias: queries by market_id column instead of event_id.
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    rows = db.conn.execute(
        """SELECT * FROM movement_log
        WHERE (market_id = ? OR event_id = ?) AND created_at >= ?
        ORDER BY created_at DESC""",
        (market_id, market_id, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def prune_old_movements(db: PolilyDB, days: int = 7) -> int:
    """Delete movement_log entries older than N days.

    Call periodically (e.g., on daemon startup) to prevent unbounded growth.
    Returns number of rows deleted.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    cursor = db.conn.execute(
        "DELETE FROM movement_log WHERE created_at < ?", (cutoff,)
    )
    deleted = cursor.rowcount
    db.conn.commit()
    if deleted > 0:
        db.conn.execute("PRAGMA optimize")
    return deleted
