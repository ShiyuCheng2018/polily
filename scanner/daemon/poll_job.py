"""Global poll job -- fetches prices for ALL active markets every 10s.

Architecture:
  - ONE global poll function, registered as IntervalTrigger in daemon
  - Step 1 (price layer): fetch CLOB + Binance concurrently -> update markets table
  - Step 2 (score refresh): recalculate mispricing + scores for scored markets
  - Step 3 (intelligence layer): for monitored events -> compute signals

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
from scanner.price_feeds import extract_crypto_asset

logger = logging.getLogger(__name__)

_SEMAPHORE_LIMIT = 100
_poll_count = 0
_poll_log: logging.Logger | None = None


def _get_poll_log() -> logging.Logger:
    """Lazy-init a dedicated file logger for poll.log."""
    global _poll_log
    if _poll_log is not None:
        return _poll_log
    import os
    log_dir = os.path.join(os.getcwd(), "data")
    os.makedirs(log_dir, exist_ok=True)
    _poll_log = logging.getLogger("polily.poll")
    _poll_log.propagate = False
    handler = logging.FileHandler(os.path.join(log_dir, "poll.log"))
    handler.setFormatter(logging.Formatter("%(message)s"))
    _poll_log.addHandler(handler)
    _poll_log.setLevel(logging.INFO)
    return _poll_log


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
    """One poll cycle: fetch all active markets, update prices, refresh scores.

    If *db* is passed directly (for testing), uses it.
    Otherwise reads from module-level _ctx.
    """
    import time as _time

    global _poll_count

    if db is None:
        if _ctx is None:
            logger.error("global_poll called before init_poller")
            return
        db = _ctx.db

    t_start = _time.monotonic()
    _poll_count += 1
    warn = False

    markets = get_active_markets(db)
    fetchable = [m for m in markets if m.clob_token_id_yes]

    if not fetchable:
        return

    # --- Step 1: Fetch CLOB + Binance concurrently ---
    crypto_symbols = _collect_crypto_symbols(db)

    t_fetch = _time.monotonic()
    results, underlying_prices = asyncio.run(
        _fetch_all(fetchable, crypto_symbols),
    )
    clob_elapsed = _time.monotonic() - t_fetch

    # Process results
    closed_count = 0
    err_count = 0
    err_by_type: dict[str, int] = {}
    closed_by_event: dict[str, list[str]] = {}

    for market, result in zip(fetchable, results, strict=True):
        if isinstance(result, httpx.HTTPStatusError):
            if result.response.status_code == 404:
                mark_market_closed(market.market_id, db)
                closed_by_event.setdefault(market.event_id, []).append(
                    market.market_id,
                )
                closed_count += 1
            else:
                err_count += 1
                key = str(result.response.status_code)
                err_by_type[key] = err_by_type.get(key, 0) + 1
            continue
        if isinstance(result, Exception):
            err_count += 1
            key = type(result).__name__
            if "timeout" in str(result).lower() or "Timeout" in type(result).__name__:
                key = "timeout"
            err_by_type[key] = err_by_type.get(key, 0) + 1
            continue
        update_market_prices(market.market_id, db=db, **result)

    db.conn.commit()

    # Close events where all sub-markets are gone
    for event_id in closed_by_event:
        all_markets = get_event_markets(event_id, db)
        if all(m.closed for m in all_markets):
            db.conn.execute(
                "UPDATE events SET closed=1, updated_at=? WHERE event_id=?",
                (datetime.now(UTC).isoformat(), event_id),
            )
    db.conn.commit()

    # --- Step 2: Refresh scores ---
    refresh_ms = 0
    refresh_n = 0
    try:
        from scanner.daemon.score_refresh import refresh_scores

        config = _ctx.config if _ctx else None
        t_refresh = _time.monotonic()
        result = refresh_scores(db, underlying_prices, config)
        refresh_ms = (_time.monotonic() - t_refresh) * 1000
        refresh_n = result.markets_refreshed
    except Exception:
        logger.exception("Score refresh failed")
        warn = True

    # --- Step 3: Intelligence layer ---
    _run_intelligence_layer(db)

    # --- Log ---
    total = _time.monotonic() - t_start
    if total > 30:
        warn = True

    plog = _get_poll_log()
    ts = datetime.now().strftime("%H:%M:%S")
    plog.info(f"── poll #{_poll_count} {'─' * 50}")

    # fetch line
    n_book = sum(1 for m in fetchable if m.spread is None or m.spread < 0.50)
    n_mid_only = len(fetchable) - n_book
    fetch_parts = [f"clob/book+mid {n_book} + mid-only {n_mid_only} = {len(fetchable)} markets {clob_elapsed:.1f}s"]
    if crypto_symbols:
        bin_status = f"binance/ticker {len(underlying_prices)}/{len(crypto_symbols)}"
        if len(underlying_prices) < len(crypto_symbols):
            bin_status += " failed"
        fetch_parts.append(bin_status)
    plog.info(f"  {ts} fetch   | {' | '.join(fetch_parts)}")

    # score line
    if refresh_n:
        plog.info(f"           score   | {refresh_n} markets rescored {refresh_ms:.0f}ms")

    # result line
    result_parts = []
    if closed_count:
        result_parts.append(f"{closed_count} closed")
    if err_count:
        result_parts.append(f"{err_count} errors")
    result_parts.append(f"total {total:.1f}s")
    if warn:
        result_parts.append("[!]")
    plog.info(f"           result  | {' | '.join(result_parts)}")

    # errors detail line (only when errors exist)
    if err_by_type:
        err_details = " | ".join(f"{k}: {v} markets" for k, v in sorted(err_by_type.items()))
        plog.info(f"           errors  | {err_details}")


def _run_intelligence_layer(db: PolilyDB) -> None:
    """Step 3: compute M/Q signals for every monitored event.

    Only runs for events with auto_monitor=1. Reads fresh prices from
    the markets table (just updated by Step 1), computes per-sub-market
    movement signals, and for negRisk events also writes event-level metrics.
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
# Helpers
# ---------------------------------------------------------------------------


def _collect_crypto_symbols(db: PolilyDB) -> set[str]:
    """Collect unique Binance symbols needed for crypto events.

    Reads event titles, extracts crypto asset pairs, converts to Binance format.
    Returns e.g. {"BTCUSDT", "ETHUSDT"}.
    """
    rows = db.conn.execute(
        "SELECT DISTINCT title FROM events WHERE market_type = 'crypto' AND closed = 0",
    ).fetchall()
    symbols = set()
    for row in rows:
        pair = extract_crypto_asset(row["title"])
        if pair:
            symbols.add(pair.replace("/", ""))  # BTC/USDT → BTCUSDT
    return symbols


# ---------------------------------------------------------------------------
# Async fetch
# ---------------------------------------------------------------------------


async def _fetch_all(markets: list, crypto_symbols: set[str] | None = None) -> tuple[list, dict[str, float]]:
    """Fetch CLOB books + midpoints + Binance tickers concurrently.

    For each market, fetches /book and /midpoint as a single unit.
    All markets + Binance run concurrently under a shared semaphore.

    Returns (results, underlying_prices).
    results: list parallel to markets (dict | Exception).
    underlying_prices: {"BTCUSDT": 71035.0, ...} — empty if no crypto.
    """
    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)

    async def _fetch_book_and_mid(client: httpx.AsyncClient, market):
        """Fetch /book + /midpoint concurrently for one market."""
        async with sem:
            book_result, mid = await asyncio.gather(
                _fetch_single_market(client, market),
                _fetch_midpoint(client, market.clob_token_id_yes),
            )
            if mid is not None:
                book_result["yes_price"] = mid
                book_result["no_price"] = round(1 - mid, 4)
                book_result["last_trade_price"] = mid
            return book_result

    async def _fetch_mid_only(client: httpx.AsyncClient, market):
        """Fetch only /midpoint for wide-spread markets (skip book)."""
        async with sem:
            mid = await _fetch_midpoint(client, market.clob_token_id_yes)
            if mid is not None:
                return {
                    "yes_price": mid,
                    "no_price": round(1 - mid, 4),
                    "last_trade_price": mid,
                }
            return {}  # no update

    async with httpx.AsyncClient(timeout=15) as client:
        # Split: narrow spread → book+midpoint, wide spread → midpoint only
        tasks = []
        for m in markets:
            if m.spread is not None and m.spread >= 0.50:
                tasks.append(_fetch_mid_only(client, m))
            else:
                tasks.append(_fetch_book_and_mid(client, m))

        binance_task = None
        if crypto_symbols:
            binance_task = asyncio.ensure_future(
                _fetch_binance_tickers(client, crypto_symbols),
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)

        underlying: dict[str, float] = {}
        if binance_task is not None:
            try:
                underlying = await binance_task
            except Exception as e:
                logger.debug("Binance ticker fetch failed: %s", e)

        return results, underlying


async def _fetch_binance_tickers(
    client: httpx.AsyncClient,
    symbols: set[str],
) -> dict[str, float]:
    """Fetch current prices from Binance for a set of symbols.

    Returns {"BTCUSDT": 71035.0, "ETHUSDT": 2198.0, ...}.
    """
    if not symbols:
        return {}
    # Binance requires compact JSON (no spaces): ["BTCUSDT","ETHUSDT"]
    symbols_json = json.dumps(sorted(symbols), separators=(",", ":"))
    resp = await client.get(
        "https://api.binance.com/api/v3/ticker/price",
        params={"symbols": symbols_json},
    )
    resp.raise_for_status()
    return {item["symbol"]: float(item["price"]) for item in resp.json()}


async def _fetch_single_market(client: httpx.AsyncClient, market) -> dict:
    """Fetch order book for one market. Returns price summary dict.

    Only fetches /book for depth data. yes_price is set later from
    the batch /midpoint fetch (see _fetch_all).

    Raises httpx.HTTPStatusError on 404 etc. so caller can handle it.
    """
    token_id = market.clob_token_id_yes

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
    spread = round(best_ask - best_bid, 4) if best_bid and best_ask else None
    bid_depth = sum(float(b["size"]) for b in bids)
    ask_depth = sum(float(a["size"]) for a in asks)

    return {
        "best_bid": best_bid,
        "best_ask": best_ask,
        "spread": spread,
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_bids": json.dumps(
            [{"price": float(b["price"]), "size": float(b["size"])} for b in bids],
        ),
        "book_asks": json.dumps(
            [{"price": float(a["price"]), "size": float(a["size"])} for a in asks],
        ),
    }


async def _fetch_midpoint(client: httpx.AsyncClient, token_id: str) -> float | None:
    """Fetch /midpoint for a single token. Returns YES price or None."""
    try:
        resp = await client.get(
            "https://clob.polymarket.com/midpoint",
            params={"token_id": token_id},
        )
        if resp.status_code == 200:
            mid = resp.json().get("mid")
            return float(mid) if mid is not None else None
    except Exception:
        pass
    return None
