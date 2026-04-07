"""Market state persistence — SQLite-backed."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from scanner.db import PolilyDB

logger = logging.getLogger(__name__)


class MarketState(BaseModel):
    """User's decision state for a market."""

    status: Literal["buy_yes", "buy_no", "watch", "pass", "closed"]
    updated_at: str = ""
    title: str = ""
    next_check_at: str | None = None
    watch_reason: str | None = None
    watch_sequence: int = 0
    price_at_watch: float | None = None
    auto_monitor: bool = False
    resolution_time: str | None = None
    market_type: str | None = None
    clob_token_id_yes: str | None = None
    condition_id: str | None = None
    wc_watch_reason: str | None = None
    wc_better_entry: str | None = None
    wc_trigger_event: str | None = None
    wc_invalidation: str | None = None
    notes: str = ""


def set_market_state(market_id: str, state: MarketState, db: PolilyDB) -> None:
    """Insert or update a market's state."""
    db.conn.execute(
        """INSERT OR REPLACE INTO market_states
        (market_id, status, title, updated_at, next_check_at, watch_reason,
         watch_sequence, price_at_watch, auto_monitor, resolution_time,
         market_type, clob_token_id_yes, condition_id,
         wc_watch_reason, wc_better_entry, wc_trigger_event, wc_invalidation, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            market_id, state.status, state.title, state.updated_at,
            state.next_check_at, state.watch_reason,
            state.watch_sequence, state.price_at_watch,
            1 if state.auto_monitor else 0, state.resolution_time,
            state.market_type, state.clob_token_id_yes, state.condition_id,
            state.wc_watch_reason, state.wc_better_entry,
            state.wc_trigger_event, state.wc_invalidation, state.notes,
        ),
    )
    db.conn.commit()


def get_market_state(market_id: str, db: PolilyDB) -> MarketState | None:
    """Get state for a single market. Returns None if not found."""
    row = db.conn.execute(
        "SELECT * FROM market_states WHERE market_id = ?", (market_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_state(row)


def get_watched_markets(db: PolilyDB) -> dict[str, MarketState]:
    """Get all markets with status='watch'."""
    rows = db.conn.execute(
        "SELECT * FROM market_states WHERE status = 'watch'",
    ).fetchall()
    return {r["market_id"]: _row_to_state(r) for r in rows}


def get_auto_monitor_watches(db: PolilyDB) -> dict[str, MarketState]:
    """Get all markets with auto_monitor enabled (any status, for display)."""
    rows = db.conn.execute(
        "SELECT * FROM market_states WHERE auto_monitor = 1",
    ).fetchall()
    return {r["market_id"]: _row_to_state(r) for r in rows}


def get_active_monitors(db: PolilyDB) -> dict[str, MarketState]:
    """Get markets that should be actively polled (auto_monitor=1, not closed/pass)."""
    rows = db.conn.execute(
        "SELECT * FROM market_states WHERE auto_monitor = 1 AND status NOT IN ('closed', 'pass')",
    ).fetchall()
    return {r["market_id"]: _row_to_state(r) for r in rows}


def is_passed(market_id: str, db: PolilyDB) -> bool:
    """Check if a market is marked as PASS."""
    state = get_market_state(market_id, db)
    return state is not None and state.status == "pass"


def _row_to_state(row) -> MarketState:
    return MarketState(
        status=row["status"],
        updated_at=row["updated_at"],
        title=row["title"],
        next_check_at=row["next_check_at"],
        watch_reason=row["watch_reason"],
        watch_sequence=row["watch_sequence"],
        price_at_watch=row["price_at_watch"],
        auto_monitor=bool(row["auto_monitor"]),
        resolution_time=row["resolution_time"],
        market_type=row["market_type"],
        clob_token_id_yes=row["clob_token_id_yes"],
        condition_id=row["condition_id"],
        wc_watch_reason=row["wc_watch_reason"],
        wc_better_entry=row["wc_better_entry"],
        wc_trigger_event=row["wc_trigger_event"],
        wc_invalidation=row["wc_invalidation"],
        notes=row["notes"],
    )
