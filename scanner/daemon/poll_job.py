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

    db.conn.commit()  # Single batch commit for all price updates

    # Check if any events need closing (all sub-markets closed) ---------------
    for event_id in closed_by_event:
        all_markets = get_event_markets(event_id, db)
        if all(m.closed for m in all_markets):
            db.conn.execute(
                "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
                (datetime.now(UTC).isoformat(), event_id),
            )
            logger.info("Event %s closed -- all sub-markets closed", event_id)

    db.conn.commit()  # Batch commit for event close updates

    # Step 2: Intelligence layer — compute signals for monitored events
    _run_intelligence_layer(db)


def _run_intelligence_layer(db: PolilyDB) -> None:
    """Step 2: compute M/Q signals for every monitored event.

    Reads fresh prices from the markets table (just updated by Step 1),
    computes per-sub-market movement signals, and for negRisk events
    also writes event-level metrics.  No AI trigger yet (stubbed).
    """
    from scanner.core.config import MovementConfig
    from scanner.core.event_store import get_event, get_event_markets
    from scanner.core.monitor_store import get_active_monitors
    from scanner.monitor.event_metrics import compute_event_metrics
    from scanner.monitor.models import MovementSignals
    from scanner.monitor.scorer import compute_movement_score
    from scanner.monitor.signals import (
        compute_book_imbalance,
        compute_price_z_score,
        compute_trade_concentration,
        compute_volume_price_confirmation,
        compute_volume_ratio,
    )
    from scanner.monitor.store import append_movement, get_event_movements

    monitored_event_ids = get_active_monitors(db)

    # Resolve MovementConfig: prefer _ctx.config, fall back to defaults
    mc: MovementConfig
    if _ctx is not None and _ctx.config is not None:
        mc = _ctx.config.movement
    else:
        mc = MovementConfig()

    for event_id in monitored_event_ids:
        try:
            event = get_event(event_id, db)
            if not event or event.closed:
                continue

            markets = get_event_markets(event_id, db)
            active_markets = [
                m for m in markets if not m.closed and m.clob_token_id_yes
            ]

            if not active_markets:
                continue

            # --- Per-sub-market signal computation ---
            for m in active_markets:
                # Build price history from previous movement_log entries
                recent = get_event_movements(event_id, db, hours=6)
                market_entries = [
                    e for e in recent if e.get("market_id") == m.market_id
                ]
                price_history = [
                    e["yes_price"]
                    for e in reversed(market_entries)
                    if e.get("yes_price") is not None
                ]

                # Signals from markets table data
                bid_depth = m.bid_depth or 0
                ask_depth = m.ask_depth or 0
                book_imbalance = compute_book_imbalance(bid_depth, ask_depth)
                price_z = compute_price_z_score(m.yes_price or 0, price_history)

                # Trade data from recent_trades JSON
                trade_sizes: list[float] = []
                if m.recent_trades:
                    try:
                        trades = json.loads(m.recent_trades)
                        trade_sizes = [
                            float(t.get("size", 0)) for t in trades
                        ]
                    except (json.JSONDecodeError, TypeError):
                        pass

                recent_volume = sum(trade_sizes)
                baseline_volume = (
                    sum(e.get("trade_volume", 0) for e in market_entries)
                    / max(len(market_entries), 1)
                )
                vol_ratio = compute_volume_ratio(recent_volume, baseline_volume)
                trade_conc = compute_trade_concentration(trade_sizes)

                prev_price = (
                    market_entries[0]["yes_price"] if market_entries else None
                )
                price_change_pct = 0.0
                if prev_price and prev_price > 0 and m.yes_price:
                    price_change_pct = (m.yes_price - prev_price) / prev_price
                vol_price_conf = compute_volume_price_confirmation(
                    price_change_pct, vol_ratio
                )

                signals = MovementSignals(
                    price_z_score=price_z,
                    volume_ratio=vol_ratio,
                    book_imbalance=book_imbalance,
                    trade_concentration=trade_conc,
                    volume_price_confirmation=vol_price_conf,
                )

                result = compute_movement_score(
                    signals, event.market_type or "other", mc
                )

                append_movement(
                    event_id=event_id,
                    market_id=m.market_id,
                    yes_price=m.yes_price,
                    no_price=m.no_price,
                    prev_yes_price=prev_price,
                    trade_volume=recent_volume,
                    bid_depth=bid_depth,
                    ask_depth=ask_depth,
                    spread=m.spread,
                    magnitude=result.magnitude,
                    quality=result.quality,
                    label=result.label,
                    db=db,
                )

            # --- Event-level metrics for negRisk events with 2+ sub-markets ---
            if event.neg_risk and len(active_markets) > 1:
                prices = {
                    m.market_id: (m.yes_price or 0) for m in active_markets
                }
                asks = {
                    m.market_id: m.best_ask
                    for m in active_markets
                    if m.best_ask
                }

                # Get previous event-level prices for TV distance / leader change
                prev_entries = get_event_movements(event_id, db, hours=1)
                prev_event_level = [
                    e for e in prev_entries if e["market_id"] is None
                ]
                prev_prices: dict[str, float] | None = None
                if prev_event_level:
                    try:
                        prev_snap = json.loads(prev_event_level[0]["snapshot"])
                        if "prices" in prev_snap:
                            prev_prices = prev_snap["prices"]
                    except (json.JSONDecodeError, TypeError):
                        pass

                metrics = compute_event_metrics(
                    prices, prev_prices=prev_prices, asks=asks
                )

                snapshot = {
                    "overround": metrics.overround,
                    "entropy": metrics.entropy,
                    "leader_id": metrics.leader_id,
                    "leader_margin": metrics.leader_margin,
                    "leader_changed": metrics.leader_changed,
                    "tv_distance": metrics.tv_distance,
                    "hhi": metrics.hhi,
                    "dutch_book_gap": metrics.dutch_book_gap,
                    "prices": prices,  # store for next comparison
                }

                append_movement(
                    event_id=event_id,
                    market_id=None,  # event-level
                    magnitude=0,
                    quality=0,
                    label="noise",
                    snapshot=json.dumps(snapshot),
                    db=db,
                )
        except Exception:
            logger.exception("Intelligence layer failed for event %s", event_id)
            continue


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
