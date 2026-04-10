"""Paper trade persistence — SQLite-backed."""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB

# Round-trip friction (buy + sell fees, spread cost).
_FRICTION_RATE = 0.04


def create_paper_trade(
    *,
    event_id: str,
    market_id: str,
    title: str,
    side: str,
    entry_price: float,
    position_size_usd: float,
    structure_score: float | None = None,
    mispricing_signal: str | None = None,
    scan_id: str | None = None,
    db: PolilyDB,
) -> str:
    """Insert a new paper trade. Returns the generated trade ID."""
    trade_id = uuid.uuid4().hex
    marked_at = datetime.now(UTC).isoformat()
    db.conn.execute(
        """
        INSERT INTO paper_trades
            (id, event_id, market_id, title, side, entry_price,
             position_size_usd, structure_score, mispricing_signal,
             scan_id, status, marked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
        """,
        (
            trade_id, event_id, market_id, title, side, entry_price,
            position_size_usd, structure_score, mispricing_signal,
            scan_id, marked_at,
        ),
    )
    db.conn.commit()
    return trade_id


def _rows_to_dicts(cursor) -> list[dict]:
    """Convert sqlite3.Row results to plain dicts."""
    return [dict(row) for row in cursor.fetchall()]


def get_open_trades(db: PolilyDB) -> list[dict]:
    """Return all open paper trades, ordered by marked_at descending."""
    cur = db.conn.execute(
        "SELECT * FROM paper_trades WHERE status = 'open' ORDER BY marked_at DESC",
    )
    return _rows_to_dicts(cur)


def get_event_open_trades(event_id: str, db: PolilyDB) -> list[dict]:
    """Return open trades for a specific event."""
    cur = db.conn.execute(
        "SELECT * FROM paper_trades WHERE event_id = ? AND status = 'open' ORDER BY marked_at DESC",
        (event_id,),
    )
    return _rows_to_dicts(cur)


def _compute_pnl(side: str, entry_price: float, position_size: float, result: str) -> float:
    """Compute paper P&L.

    Win (side matches result): shares redeemed at $1 each.
        pnl = (position_size / entry_price) * 1.0 - position_size
    Lose (side != result): total loss.
        pnl = -position_size
    """
    won = side == result
    if won:
        return position_size / entry_price - position_size
    return -position_size


def resolve_trade(trade_id: str, *, result: str, db: PolilyDB) -> None:
    """Resolve a trade: set status, compute P&L and friction-adjusted P&L."""
    cur = db.conn.execute(
        "SELECT side, entry_price, position_size_usd FROM paper_trades WHERE id = ?",
        (trade_id,),
    )
    row = cur.fetchone()
    if row is None:
        msg = f"Trade {trade_id} not found"
        raise ValueError(msg)

    side = row["side"]
    entry_price = row["entry_price"]
    position_size = row["position_size_usd"]

    pnl = _compute_pnl(side, entry_price, position_size, result)
    friction_pnl = pnl - (position_size * _FRICTION_RATE)
    resolved_at = datetime.now(UTC).isoformat()

    db.conn.execute(
        """
        UPDATE paper_trades
        SET status = 'resolved',
            resolved_result = ?,
            paper_pnl = ?,
            friction_adjusted_pnl = ?,
            resolved_at = ?
        WHERE id = ?
        """,
        (result, pnl, friction_pnl, resolved_at, trade_id),
    )
    db.conn.commit()


def get_resolved_trades(db: PolilyDB) -> list[dict]:
    """Return all resolved paper trades, ordered by resolved_at descending."""
    cur = db.conn.execute(
        "SELECT * FROM paper_trades WHERE status = 'resolved' ORDER BY resolved_at DESC",
    )
    return _rows_to_dicts(cur)


def get_trade_stats(db: PolilyDB) -> dict:
    """Return aggregate statistics for all paper trades.

    Returns dict with keys: open, resolved, total, total_pnl,
    total_friction_pnl, win_rate.
    """
    cur = db.conn.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'open') AS open_count,
            COUNT(*) FILTER (WHERE status = 'resolved') AS resolved_count,
            COUNT(*) AS total,
            COALESCE(SUM(paper_pnl) FILTER (WHERE status = 'resolved'), 0.0) AS total_pnl,
            COALESCE(SUM(friction_adjusted_pnl) FILTER (WHERE status = 'resolved'), 0.0) AS total_friction_pnl,
            COUNT(*) FILTER (WHERE status = 'resolved' AND paper_pnl > 0) AS wins
        FROM paper_trades
        """,
    )
    row = cur.fetchone()
    resolved = row["resolved_count"]
    wins = row["wins"]
    return {
        "open": row["open_count"],
        "resolved": resolved,
        "total": row["total"],
        "total_pnl": row["total_pnl"],
        "total_friction_pnl": row["total_friction_pnl"],
        "win_rate": (wins / resolved) if resolved > 0 else 0.0,
    }
