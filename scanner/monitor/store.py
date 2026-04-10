"""Persist and query movement detection results."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from scanner.monitor.models import MovementResult

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB


def append_movement(
    market_id: str,
    result: MovementResult,
    *,
    yes_price: float | None = None,
    prev_yes_price: float | None = None,
    trade_volume: float = 0.0,
    bid_depth: float = 0.0,
    ask_depth: float = 0.0,
    spread: float | None = None,
    triggered_analysis: bool = False,
    db: PolilyDB,
) -> None:
    """Append a movement log entry."""
    snapshot = json.dumps(result.signals.model_dump(), ensure_ascii=False)
    db.conn.execute(
        """INSERT INTO movement_log
        (market_id, created_at, yes_price, prev_yes_price, trade_volume,
         bid_depth, ask_depth, spread,
         magnitude, quality, label, triggered_analysis, snapshot)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            market_id,
            datetime.now(UTC).isoformat(),
            yes_price,
            prev_yes_price,
            trade_volume,
            bid_depth,
            ask_depth,
            spread,
            result.magnitude,
            result.quality,
            result.label,
            1 if triggered_analysis else 0,
            snapshot,
        ),
    )
    db.conn.commit()


def get_recent_movements(market_id: str, db: PolilyDB, hours: int = 6) -> list[dict]:
    """Get movement log entries within the last N hours."""
    cutoff = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    rows = db.conn.execute(
        """SELECT * FROM movement_log
        WHERE market_id = ? AND created_at >= ?
        ORDER BY created_at DESC""",
        (market_id, cutoff),
    ).fetchall()
    return [dict(r) for r in rows]


def get_movement_summary(market_id: str, db: PolilyDB, hours: int = 6) -> str | None:
    """Build a human-readable movement summary for AI context.

    Returns None if no movements in the window.
    """
    entries = get_recent_movements(market_id, db, hours=hours)
    if not entries:
        return None

    parts = [f"--- Movement Log (last {hours}h, {len(entries)} entries) ---"]
    for e in reversed(entries):  # chronological order
        ts = e["created_at"][:16]  # trim to minute
        price = e.get("yes_price", "?")
        prev = e.get("prev_yes_price", "?")
        mag = e["magnitude"]
        qual = e["quality"]
        label = e["label"]
        triggered = " [TRIGGERED AI]" if e.get("triggered_analysis") else ""
        parts.append(
            f"  {ts}: {prev} → {price} | M={mag:.0f} Q={qual:.0f} [{label}]{triggered}"
        )

    return "\n".join(parts)


def get_today_analysis_count(market_id: str, db: PolilyDB) -> int:
    """Count how many times a market triggered AI analysis today."""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    row = db.conn.execute(
        """SELECT COUNT(*) FROM movement_log
        WHERE market_id = ? AND triggered_analysis = 1
        AND created_at >= ?""",
        (market_id, today),
    ).fetchone()
    return row[0] if row else 0


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


def get_latest_movement(market_id: str, db: PolilyDB) -> dict | None:
    """Get the most recent movement_log entry for a market."""
    row = db.conn.execute(
        """SELECT * FROM movement_log
        WHERE market_id = ?
        ORDER BY id DESC LIMIT 1""",
        (market_id,),
    ).fetchone()
    return dict(row) if row else None


def get_price_status(
    market_id: str, db: PolilyDB, *, watch_price: float | None = None,
    significant_threshold: float = 5.0,
) -> dict | None:
    """Get structured price status for TUI display.

    Returns dict with current_price, watch_price, change_pct,
    magnitude, quality, label, significant_change.
    Returns None if no movement data exists.
    """
    latest = get_latest_movement(market_id, db)
    if latest is None:
        return None

    current_price = latest.get("yes_price") or 0.0
    change_pct = 0.0
    if watch_price and watch_price > 0:
        change_pct = (current_price - watch_price) / watch_price * 100

    return {
        "current_price": current_price,
        "watch_price": watch_price,
        "change_pct": change_pct,
        "magnitude": latest["magnitude"],
        "quality": latest["quality"],
        "label": latest["label"],
        "trade_volume": latest.get("trade_volume", 0.0),
        "bid_depth": latest.get("bid_depth", 0.0),
        "ask_depth": latest.get("ask_depth", 0.0),
        "spread": latest.get("spread"),
        "updated_at": latest["created_at"],
        "significant_change": abs(change_pct) >= significant_threshold,
    }
