"""Event and market persistence — SQLite-backed."""
from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB


# ---------------------------------------------------------------------------
# Pydantic row models
# ---------------------------------------------------------------------------

class EventRow(BaseModel):
    """Represents a row in the events table."""

    event_id: str
    title: str
    slug: str | None = None
    description: str | None = None
    resolution_source: str | None = None
    neg_risk: bool = False
    neg_risk_market_id: str | None = None
    neg_risk_augmented: bool = False
    market_count: int = 1
    start_date: str | None = None
    end_date: str | None = None
    image: str | None = None
    volume: float | None = None
    liquidity: float | None = None
    open_interest: float | None = None
    competitive: float | None = None
    tags: str = "[]"
    market_type: str | None = None
    event_metadata: str | None = None
    structure_score: float | None = None
    tier: str | None = None
    user_status: str | None = None
    active: int = 1
    closed: int = 0
    created_at: str | None = None
    updated_at: str = ""


class MarketRow(BaseModel):
    """Represents a row in the markets table."""

    market_id: str
    event_id: str
    question: str
    slug: str | None = None
    description: str | None = None
    group_item_title: str | None = None
    group_item_threshold: str | None = None
    outcomes: str = '["Yes","No"]'
    condition_id: str | None = None
    question_id: str | None = None
    clob_token_id_yes: str | None = None
    clob_token_id_no: str | None = None
    neg_risk: bool = False
    neg_risk_request_id: str | None = None
    neg_risk_other: bool = False
    resolution_source: str | None = None
    end_date: str | None = None
    volume: float | None = None
    liquidity: float | None = None
    order_min_tick_size: float | None = None
    structure_score: float | None = None
    yes_price: float | None = None
    no_price: float | None = None
    best_bid: float | None = None
    best_ask: float | None = None
    spread: float | None = None
    last_trade_price: float | None = None
    bid_depth: float | None = None
    ask_depth: float | None = None
    book_bids: str | None = None
    book_asks: str | None = None
    recent_trades: str | None = None
    accepting_orders: int = 1
    active: int = 1
    closed: int = 0
    created_at: str | None = None
    updated_at: str = ""


# ---------------------------------------------------------------------------
# Event CRUD
# ---------------------------------------------------------------------------

# Columns inserted for events (excludes user_status, structure_score, tier
# which are managed by other flows).
_EVENT_INSERT_COLS = (
    "event_id", "title", "slug", "description", "resolution_source",
    "neg_risk", "neg_risk_market_id", "neg_risk_augmented", "market_count",
    "start_date", "end_date", "image", "volume", "liquidity", "open_interest",
    "competitive", "tags", "market_type", "event_metadata", "active", "closed",
    "created_at", "updated_at",
)

# On conflict, update these columns (NOT user_status, structure_score, tier).
_EVENT_UPDATE_COLS = tuple(c for c in _EVENT_INSERT_COLS if c != "event_id")


def upsert_event(event: EventRow, db: PolilyDB) -> None:
    """Insert or update an event. Preserves user_status, structure_score, tier."""
    placeholders = ", ".join("?" for _ in _EVENT_INSERT_COLS)
    conflict_set = ", ".join(f"{c}=excluded.{c}" for c in _EVENT_UPDATE_COLS)
    sql = f"""
        INSERT INTO events ({', '.join(_EVENT_INSERT_COLS)})
        VALUES ({placeholders})
        ON CONFLICT(event_id) DO UPDATE SET {conflict_set}
    """
    values = tuple(getattr(event, c) for c in _EVENT_INSERT_COLS)
    db.conn.execute(sql, values)
    db.conn.commit()


# All columns in the events table (for SELECT *).
_EVENT_ALL_COLS = (
    "event_id", "title", "slug", "description", "resolution_source",
    "neg_risk", "neg_risk_market_id", "neg_risk_augmented", "market_count",
    "start_date", "end_date", "image", "volume", "liquidity", "open_interest",
    "competitive", "tags", "market_type", "event_metadata",
    "structure_score", "tier", "user_status",
    "active", "closed", "created_at", "updated_at",
)


def _row_to_event(row: dict) -> EventRow:
    """Convert a sqlite3.Row to EventRow."""
    return EventRow(**{k: row[k] for k in _EVENT_ALL_COLS})


def get_event(event_id: str, db: PolilyDB) -> EventRow | None:
    """Fetch a single event by ID, or None if not found."""
    cur = db.conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_event(row)


# ---------------------------------------------------------------------------
# Market CRUD
# ---------------------------------------------------------------------------

# Columns inserted for markets (excludes structure_score which is set by
# the scoring pipeline).
_MARKET_INSERT_COLS = (
    "market_id", "event_id", "question", "slug", "description",
    "group_item_title", "group_item_threshold", "outcomes",
    "condition_id", "question_id", "clob_token_id_yes", "clob_token_id_no",
    "neg_risk", "neg_risk_request_id", "neg_risk_other",
    "resolution_source", "end_date", "volume", "liquidity",
    "order_min_tick_size",
    "yes_price", "no_price", "best_bid", "best_ask", "spread",
    "last_trade_price", "bid_depth", "ask_depth",
    "book_bids", "book_asks", "recent_trades",
    "accepting_orders", "active", "closed",
    "created_at", "updated_at",
)

_MARKET_UPDATE_COLS = tuple(c for c in _MARKET_INSERT_COLS if c != "market_id")

_MARKET_ALL_COLS = (
    "market_id", "event_id", "question", "slug", "description",
    "group_item_title", "group_item_threshold", "outcomes",
    "condition_id", "question_id", "clob_token_id_yes", "clob_token_id_no",
    "neg_risk", "neg_risk_request_id", "neg_risk_other",
    "resolution_source", "end_date", "volume", "liquidity",
    "order_min_tick_size", "structure_score",
    "yes_price", "no_price", "best_bid", "best_ask", "spread",
    "last_trade_price", "bid_depth", "ask_depth",
    "book_bids", "book_asks", "recent_trades",
    "accepting_orders", "active", "closed",
    "created_at", "updated_at",
)


def _row_to_market(row: dict) -> MarketRow:
    """Convert a sqlite3.Row to MarketRow."""
    return MarketRow(**{k: row[k] for k in _MARKET_ALL_COLS})


def upsert_market(market: MarketRow, db: PolilyDB) -> None:
    """Insert or update a market. Preserves structure_score."""
    placeholders = ", ".join("?" for _ in _MARKET_INSERT_COLS)
    conflict_set = ", ".join(f"{c}=excluded.{c}" for c in _MARKET_UPDATE_COLS)
    sql = f"""
        INSERT INTO markets ({', '.join(_MARKET_INSERT_COLS)})
        VALUES ({placeholders})
        ON CONFLICT(market_id) DO UPDATE SET {conflict_set}
    """
    values = tuple(getattr(market, c) for c in _MARKET_INSERT_COLS)
    db.conn.execute(sql, values)
    db.conn.commit()


def get_market(market_id: str, db: PolilyDB) -> MarketRow | None:
    """Fetch a single market by ID, or None if not found."""
    cur = db.conn.execute("SELECT * FROM markets WHERE market_id = ?", (market_id,))
    row = cur.fetchone()
    if row is None:
        return None
    return _row_to_market(row)


def get_event_markets(event_id: str, db: PolilyDB) -> list[MarketRow]:
    """Fetch all markets belonging to an event."""
    cur = db.conn.execute(
        "SELECT * FROM markets WHERE event_id = ? ORDER BY market_id",
        (event_id,),
    )
    return [_row_to_market(row) for row in cur.fetchall()]


def get_active_markets(db: PolilyDB) -> list[MarketRow]:
    """Fetch all active, non-closed markets."""
    cur = db.conn.execute(
        "SELECT * FROM markets WHERE active = 1 AND closed = 0 ORDER BY market_id",
    )
    return [_row_to_market(row) for row in cur.fetchall()]


def update_market_prices(
    market_id: str,
    *,
    db: PolilyDB,
    yes_price: float | None = None,
    no_price: float | None = None,
    best_bid: float | None = None,
    best_ask: float | None = None,
    spread: float | None = None,
    last_trade_price: float | None = None,
    bid_depth: float | None = None,
    ask_depth: float | None = None,
    book_bids: str | None = None,
    book_asks: str | None = None,
    recent_trades: str | None = None,
) -> None:
    """Update price-related columns for a market.

    Accepts both numeric fields and JSON-string fields (book_bids,
    book_asks, recent_trades) written by the global poll job.
    """
    from datetime import UTC, datetime

    updates: list[str] = []
    values: list[object] = []
    fields = {
        "yes_price": yes_price,
        "no_price": no_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "last_trade_price": last_trade_price,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_bids": book_bids,
        "book_asks": book_asks,
        "recent_trades": recent_trades,
    }
    for col, val in fields.items():
        if val is not None:
            updates.append(f"{col} = ?")
            values.append(val)
    if not updates:
        return
    updates.append("updated_at = ?")
    values.append(datetime.now(UTC).isoformat())
    values.append(market_id)
    sql = f"UPDATE markets SET {', '.join(updates)} WHERE market_id = ?"
    db.conn.execute(sql, tuple(values))
    db.conn.commit()


def mark_market_closed(market_id: str, db: PolilyDB) -> None:
    """Mark a market as closed and no longer accepting orders."""
    db.conn.execute(
        "UPDATE markets SET closed = 1, accepting_orders = 0 WHERE market_id = ?",
        (market_id,),
    )
    db.conn.commit()
