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
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    get_event_markets,
    mark_market_closed,
    update_market_prices,
)
from scanner.price_feeds import extract_crypto_asset

logger = logging.getLogger(__name__)

# Max concurrent market fetches. Each slot holds 4 requests
# (/book + /midpoint + /price BUY + /price SELL).
_SEMAPHORE_LIMIT = 100
_poll_count = 0  # Safe: poll executor is single-threaded (APScheduler config)
_poll_log: logging.Logger | None = None


def _get_poll_log() -> logging.Logger:
    """Lazy-init a dedicated file logger for poll.log."""
    global _poll_log
    if _poll_log is not None:
        return _poll_log
    from pathlib import Path
    # Use project root (3 levels up from this file) to avoid cwd dependency
    project_root = Path(__file__).resolve().parent.parent.parent
    log_dir = str(project_root / "data")
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    _poll_log = logging.getLogger("polily.poll")
    _poll_log.propagate = False
    handler = logging.FileHandler(str(Path(log_dir) / "poll.log"))
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

    markets = _get_monitored_markets(db)
    fetchable = [m for m in markets if m.clob_token_id_yes]

    if not fetchable:
        return

    # --- Step 1: Fetch CLOB + Binance concurrently ---
    crypto_symbols = _collect_crypto_symbols(db)

    t_fetch = _time.monotonic()
    results, underlying_prices, trades_by_id = asyncio.run(
        _fetch_all(fetchable, crypto_symbols),
    )
    clob_elapsed = _time.monotonic() - t_fetch

    # Process results
    closed_count = 0
    err_count = 0
    err_by_type: dict[str, int] = {}
    closed_by_event: dict[str, list[str]] = {}
    price_ok = 0  # markets with midpoint price
    book_ok = 0   # markets with orderbook depth

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
        if result.get("yes_price") is not None:
            price_ok += 1
        if result.get("bid_depth") and result.get("bid_depth") > 0:
            book_ok += 1
        update_market_prices(market.market_id, db=db, **result)

    # Write trades to markets.recent_trades
    trades_ok = 0
    for market in fetchable:
        trades = trades_by_id.get(market.market_id)
        if trades:
            db.conn.execute(
                "UPDATE markets SET recent_trades = ? WHERE market_id = ?",
                (json.dumps(trades), market.market_id),
            )
            trades_ok += 1

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
    fetch_parts = [f"clob {len(fetchable)} markets {clob_elapsed:.1f}s"]
    if crypto_symbols:
        bin_status = f"binance/ticker {len(underlying_prices)}/{len(crypto_symbols)}"
        if len(underlying_prices) < len(crypto_symbols):
            bin_status += " failed"
        fetch_parts.append(bin_status)
    plog.info(f"  {ts} fetch   | {' | '.join(fetch_parts)}")

    # score line
    if refresh_n:
        plog.info(f"           score   | {refresh_n} markets rescored {refresh_ms:.0f}ms")

    # check line — data completeness
    n_total = len(fetchable)
    check_parts = [f"price: {price_ok}/{n_total}", f"book: {book_ok}/{n_total}", f"trades: {trades_ok}/{n_total}", f"score: {refresh_n}/{n_total}"]
    if underlying_prices:
        bin_parts = [f"{sym.replace('USDT','')} ${p:,.0f}" for sym, p in underlying_prices.items()]
        check_parts.append(f"binance: {' '.join(bin_parts)}")
    plog.info(f"           check   | {' | '.join(check_parts)}")

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
            _MIN_HISTORY = 5  # minimum entries for meaningful signals
            _STALE_SECONDS = 600  # 10 min — data older than this is stale

            # Fetch once per event (not per market)
            recent = get_event_movements(event_id, db, hours=6)

            for m in active_markets:
                market_entries = [
                    e for e in recent if e.get("market_id") == m.market_id
                ]

                # Guard: check data sufficiency and freshness
                is_cold = len(market_entries) < _MIN_HISTORY
                is_stale = False
                if market_entries:
                    latest_ts = market_entries[0].get("created_at", "")
                    try:
                        latest_dt = datetime.fromisoformat(latest_ts)
                        if latest_dt.tzinfo is None:
                            latest_dt = latest_dt.replace(tzinfo=UTC)
                        age = (datetime.now(UTC) - latest_dt).total_seconds()
                        is_stale = age > _STALE_SECONDS
                    except (ValueError, TypeError):
                        is_stale = True

                if is_cold or is_stale:
                    # Write noise entry — just record price, no signal computation
                    append_movement(
                        event_id=event_id, market_id=m.market_id,
                        yes_price=m.yes_price, no_price=m.no_price,
                        bid_depth=m.bid_depth or 0, ask_depth=m.ask_depth or 0,
                        spread=m.spread, magnitude=0, quality=0, label="noise",
                        db=db,
                    )
                    continue

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

            # --- Event-level trigger: check if AI analysis should fire ---
            _check_event_trigger(event_id, active_markets, mc, db)

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

    # Batch commit all movement_log entries
    db.conn.commit()


def _check_event_trigger(
    event_id: str,
    active_markets: list,
    mc,
    db: PolilyDB,
) -> None:
    """Check if event-level movement should trigger AI analysis.

    Aggregates max(M) and max(Q) across all sub-markets in the latest tick,
    then checks: should_trigger AND cooldown AND daily limit.
    If all pass, submits AI analysis to the ai executor.
    """
    from scanner.monitor.models import MovementResult
    from scanner.monitor.store import get_event_latest, get_today_analysis_count

    # Get latest movement entries for this event's markets
    latest = get_event_latest(event_id, db)
    if not latest:
        return

    # Aggregate: max M and Q across sub-markets in latest tick (within 60s)
    cutoff = (datetime.now(UTC) - timedelta(seconds=60)).isoformat()
    recent = db.conn.execute(
        """SELECT magnitude, quality FROM movement_log
        WHERE event_id = ? AND market_id IS NOT NULL
        AND created_at >= ?
        ORDER BY created_at DESC""",
        (event_id, cutoff),
    ).fetchall()

    if not recent:
        return

    max_m = max(r["magnitude"] for r in recent)
    max_q = max(r["quality"] for r in recent)

    # Check trigger threshold
    agg = MovementResult(magnitude=max_m, quality=max_q)
    if not agg.should_trigger(mc.magnitude_threshold, mc.quality_threshold):
        return

    # Check cooldown: last triggered analysis for this event
    last_triggered = db.conn.execute(
        """SELECT created_at FROM movement_log
        WHERE event_id = ? AND triggered_analysis = 1
        ORDER BY created_at DESC LIMIT 1""",
        (event_id,),
    ).fetchone()

    if last_triggered:
        try:
            last_dt = datetime.fromisoformat(last_triggered["created_at"])
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - last_dt).total_seconds()
            if age < agg.cooldown_seconds:
                logger.debug(
                    "Event %s trigger skipped: cooldown (%ds < %ds)",
                    event_id, int(age), agg.cooldown_seconds,
                )
                return
        except (ValueError, TypeError):
            pass

    # Check daily limit
    today_count = get_today_analysis_count(event_id, db)
    if today_count >= mc.daily_analysis_limit:
        logger.debug(
            "Event %s trigger skipped: daily limit (%d/%d)",
            event_id, today_count, mc.daily_analysis_limit,
        )
        return

    # --- Trigger AI analysis ---
    logger.info(
        "Movement trigger for event %s: M=%.0f Q=%.0f (%s)",
        event_id, max_m, max_q, agg.label,
    )

    # Mark triggered in movement_log (the highest-scoring market entry)
    db.conn.execute(
        """UPDATE movement_log SET triggered_analysis = 1
        WHERE event_id = ? AND market_id IS NOT NULL
        AND id = (SELECT id FROM movement_log
                  WHERE event_id = ? AND market_id IS NOT NULL
                  ORDER BY created_at DESC LIMIT 1)""",
        (event_id, event_id),
    )

    # Submit to ai executor
    if _ctx and _ctx.scheduler:
        try:
            from scanner.daemon.recheck import recheck_event
            from scanner.tui.service import ScanService

            service = ScanService(db)
            _ctx.scheduler.add_job(
                recheck_event,
                id=f"movement_trigger_{event_id}",
                executor="ai",
                replace_existing=True,
                kwargs={
                    "event_id": event_id,
                    "db": db,
                    "service": service,
                    "trigger_source": "movement",
                },
            )
        except Exception:
            logger.exception("Failed to submit movement-triggered analysis for %s", event_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_monitored_markets(db: PolilyDB) -> list:
    """Get active markets only from monitored events."""
    rows = db.conn.execute(
        """SELECT m.* FROM markets m
        JOIN event_monitors em ON m.event_id = em.event_id
        WHERE m.active = 1 AND m.closed = 0
        AND em.auto_monitor = 1
        ORDER BY m.market_id""",
    ).fetchall()
    from scanner.core.event_store import MarketRow
    return [MarketRow.model_validate(dict(r)) for r in rows]


def _collect_crypto_symbols(db: PolilyDB) -> set[str]:
    """Collect unique Binance symbols needed for monitored crypto events.

    Returns e.g. {"BTCUSDT", "ETHUSDT"}.
    """
    rows = db.conn.execute(
        """SELECT DISTINCT e.title FROM events e
        JOIN event_monitors em ON e.event_id = em.event_id
        WHERE e.market_type = 'crypto' AND e.closed = 0
        AND em.auto_monitor = 1""",
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


async def _fetch_all(
    markets: list, crypto_symbols: set[str] | None = None,
) -> tuple[list, dict[str, float], dict[str, list]]:
    """Fetch CLOB data + Binance tickers + trades concurrently.

    Returns (results, underlying_prices, trades_by_market_id).
    results: list parallel to markets (dict | Exception).
    underlying_prices: {"BTCUSDT": 71035.0, ...} — empty if no crypto.
    trades_by_market_id: {"m1": [{"price":..., "size":..., "side":...}, ...], ...}
    """
    from scanner.core.clob import fetch_clob_market_data

    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)

    async def _fetch_one(client: httpx.AsyncClient, market):
        async with sem:
            return await fetch_clob_market_data(client, market.clob_token_id_yes)

    async with httpx.AsyncClient(timeout=15) as client:
        clob_tasks = [_fetch_one(client, m) for m in markets]

        binance_task = None
        if crypto_symbols:
            binance_task = asyncio.ensure_future(
                _fetch_binance_tickers(client, crypto_symbols),
            )

        trades_task = asyncio.ensure_future(
            _fetch_trades_batch(client, markets),
        )

        results = await asyncio.gather(*clob_tasks, return_exceptions=True)

        underlying: dict[str, float] = {}
        if binance_task is not None:
            try:
                underlying = await binance_task
            except Exception as e:
                logger.debug("Binance ticker fetch failed: %s", e)

        trades_by_id: dict[str, list] = {}
        try:
            trades_by_id = await trades_task
        except Exception as e:
            logger.debug("Trades batch fetch failed: %s", e)

        return results, underlying, trades_by_id


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


_TRADES_SEM_LIMIT = 5  # Data API is slower; limit concurrency
_DATA_API_BASE = "https://data-api.polymarket.com"


async def _fetch_trades_batch(
    client: httpx.AsyncClient,
    markets: list,
) -> dict[str, list]:
    """Fetch recent trades for all markets from Data API.

    Uses condition_id (not token_id). Concurrency limited to 5.
    Returns {market_id: [{"price":..., "size":..., "side":...}, ...]}.
    """
    sem = asyncio.Semaphore(_TRADES_SEM_LIMIT)
    result: dict[str, list] = {}

    async def _fetch_one(market):
        cid = market.condition_id
        if not cid:
            return
        async with sem:
            try:
                resp = await client.get(
                    f"{_DATA_API_BASE}/trades",
                    params={"market": cid, "limit": 20},
                )
                if resp.status_code != 200:
                    return
                data = resp.json()
                if isinstance(data, list):
                    raw = data
                elif isinstance(data, dict):
                    raw = data.get("data", [])
                else:
                    return
                result[market.market_id] = [
                    {
                        "price": float(t.get("price", 0)),
                        "size": float(t.get("size", 0)),
                        "side": t.get("side", ""),
                    }
                    for t in raw
                    if t.get("price") is not None
                ]
            except Exception as e:
                logger.debug("Trades fetch failed for %s: %s", market.market_id, e)

    await asyncio.gather(*[_fetch_one(m) for m in markets])
    return result
