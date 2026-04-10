"""Global poll job -- fetches prices for ALL active markets every 10s.

Architecture:
  - ONE global poll function, registered as IntervalTrigger in daemon
  - Step 1 (price layer): asyncio.gather all CLOB book+trades -> update markets table
  - Step 2 (intelligence layer): for monitored events -> compute signals (Task 3.2)

Module-level _ctx pattern (PollerContext) for db/config/scheduler access.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    get_active_markets,
    get_event_markets,
    mark_market_closed,
    update_market_prices,
)

logger = logging.getLogger(__name__)

_SEMAPHORE_LIMIT = 100


@dataclass(frozen=True)
class PollerContext:
    """Immutable context -- swapped atomically to avoid thread-safety races."""

    db: PolilyDB
    config: Any = None
    scheduler: Any = None


# Single reference (set once on daemon startup via init_poller)
_ctx: PollerContext | None = None


def init_poller(db: PolilyDB, config: Any = None, scheduler: Any = None) -> None:
    """Initialize module-level context."""
    global _ctx
    _ctx = PollerContext(db=db, config=config, scheduler=scheduler)


def global_poll(db: PolilyDB | None = None) -> None:
    """One poll cycle: fetch all active markets, update prices.

    If *db* is passed directly (for testing), uses it.
    Otherwise reads from module-level _ctx.
    """
    if db is None:
        if _ctx is None:
            logger.error("global_poll called before init_poller")
            return
        db = _ctx.db

    markets = get_active_markets(db)
    # Filter to markets with CLOB tokens (cannot fetch without one)
    fetchable = [m for m in markets if m.clob_token_id_yes]

    if not fetchable:
        return

    # Fetch all concurrently via asyncio.gather + Semaphore
    results = asyncio.run(_fetch_all(fetchable))

    # Process results ---------------------------------------------------------
    closed_by_event: dict[str, list[str]] = {}  # event_id -> [closed market_ids]

    for market, result in zip(fetchable, results, strict=True):
        if isinstance(result, httpx.HTTPStatusError):
            if result.response.status_code == 404:
                mark_market_closed(market.market_id, db)
                closed_by_event.setdefault(market.event_id, []).append(
                    market.market_id,
                )
                logger.info("Market %s 404 -- marked closed", market.market_id)
            else:
                logger.warning(
                    "Poll error %s for %s",
                    result.response.status_code,
                    market.market_id,
                )
            continue
        if isinstance(result, Exception):
            logger.warning("Poll failed for %s: %s", market.market_id, result)
            continue

        # Update prices in markets table
        update_market_prices(market.market_id, db=db, **result)

    # Check if any events need closing (all sub-markets closed) ---------------
    for event_id in closed_by_event:
        all_markets = get_event_markets(event_id, db)
        if all(m.closed for m in all_markets):
            db.conn.execute(
                "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
                (datetime.now(UTC).isoformat(), event_id),
            )
            db.conn.commit()
            logger.info("Event %s closed -- all sub-markets closed", event_id)

    # Step 2: Intelligence layer (Task 3.2 -- stub for now)
    # _run_intelligence_layer(db)


# ---------------------------------------------------------------------------
# Async fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_all(markets: list) -> list:
    """Fetch book + trades for all markets concurrently."""
    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)

    async def _bounded_fetch(client: httpx.AsyncClient, market):
        async with sem:
            return await _fetch_single_market(client, market)

    async with httpx.AsyncClient(timeout=15) as client:
        tasks = [_bounded_fetch(client, m) for m in markets]
        return await asyncio.gather(*tasks, return_exceptions=True)


async def _fetch_single_market(client: httpx.AsyncClient, market) -> dict:
    """Fetch book + trades for one market. Returns price summary dict.

    Raises httpx.HTTPStatusError on 404 etc. so caller can handle it.
    """
    token_id = market.clob_token_id_yes

    # --- Fetch order book ---
    book_resp = await client.get(
        "https://clob.polymarket.com/book",
        params={"token_id": token_id},
    )
    book_resp.raise_for_status()
    book = book_resp.json()

    bids = book.get("bids", [])
    asks = book.get("asks", [])

    best_bid = float(bids[0]["price"]) if bids else None
    best_ask = float(asks[0]["price"]) if asks else None
    yes_price = (best_bid + best_ask) / 2 if best_bid and best_ask else None
    no_price = round(1 - yes_price, 4) if yes_price else None
    spread = round(best_ask - best_bid, 4) if best_bid and best_ask else None
    bid_depth = sum(float(b["size"]) for b in bids)
    ask_depth = sum(float(a["size"]) for a in asks)
    last_trade = book.get("last_trade_price")

    # --- Fetch recent trades (optional, don't fail the poll) ---
    trades_data: list[dict] = []
    if market.condition_id:
        try:
            trades_resp = await client.get(
                "https://data-api.polymarket.com/trades",
                params={"market": market.condition_id, "limit": 50},
            )
            if trades_resp.status_code == 200:
                raw = trades_resp.json()
                trades_data = raw if isinstance(raw, list) else raw.get("data", [])
        except Exception:
            pass  # trades are optional

    return {
        "yes_price": yes_price,
        "no_price": no_price,
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "last_trade_price": float(last_trade) if last_trade else None,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_bids": json.dumps(
            [{"price": float(b["price"]), "size": float(b["size"])} for b in bids],
        ),
        "book_asks": json.dumps(
            [{"price": float(a["price"]), "size": float(a["size"])} for a in asks],
        ),
        "recent_trades": json.dumps(
            [
                {
                    "price": float(t.get("price", 0)),
                    "size": float(t.get("size", 0)),
                    "side": t.get("side", ""),
                    "timestamp": str(t.get("timestamp", "")),
                }
                for t in trades_data[:50]
            ],
        ),
    }
