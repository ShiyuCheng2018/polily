"""Core scan pipeline: fetch → filter → classify → score → mispricing → [AI] → tier."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import TYPE_CHECKING

import httpx

from scanner.api import CLOB_BASE, parse_clob_book
from scanner.core.config import ScannerConfig
from scanner.core.models import Market
from scanner.orderbook import is_stale_book
from scanner.scan.mispricing import MispricingResult, detect_mispricing
from scanner.scan.reporting import ScoredCandidate, TierResult, classify_tiers
from scanner.scan.scoring import compute_structure_score

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB

logger = logging.getLogger(__name__)


@contextmanager
def _timed_status(console, message: str):
    """Spinner with live elapsed time, like Claude Code CLI."""
    start = time.time()
    stop_event = threading.Event()

    def _update():
        while not stop_event.is_set():
            elapsed = time.time() - start
            status.update(f"[bold]{message}[/bold] [dim]{elapsed:.1f}s[/dim]")
            stop_event.wait(0.5)

    status = console.status(f"[bold]{message}[/bold]")
    status.start()
    updater = threading.Thread(target=_update, daemon=True)
    updater.start()
    try:
        yield
    finally:
        stop_event.set()
        updater.join(timeout=1)
        status.stop()
        elapsed = time.time() - start
        console.print(f" [dim]{message} [{elapsed:.1f}s][/dim]")


def run_scan_pipeline(
    markets: list[Market],
    config: ScannerConfig,
    *,
    db: PolilyDB | None = None,
    event_rows: list | None = None,
    progress_cb=None,
) -> TierResult:
    """Run the full scan pipeline on a list of markets.

    Steps:
    1. Hard filters (deterministic)
    2. Market type classification (keyword or AI-enhanced)
    3. Beauty score computation (deterministic, uses AI objectivity if available)
    4. Mispricing detection (math model)
    5. AI narrative generation (for Tier A + top Tier B)
    6. Tier classification (A/B/C)
    """
    def _report(name, status, detail=""):
        if progress_cb:
            progress_cb(name, status, detail)

    # Phase 4: Hard filters
    import os

    from rich.console import Console
    # In TUI mode, use a silent console to avoid terminal corruption
    if os.environ.get("POLILY_TUI"):
        _console = Console(file=__import__("io").StringIO(), stderr=False)
    else:
        _console = Console()
    # Event-level filtering (replaces per-market filter)
    # --- Stage 1: Lightweight event filter (volume + noise + expiry) ---
    from scanner.scan.filters import filter_events
    _report("筛选", "start")

    # Pair events with their markets
    event_map = {}
    for er in (event_rows or []):
        event_map[er.event_id] = er
    market_by_event: dict[str, list[Market]] = {}
    for m in markets:
        eid = getattr(m, "event_id", None)
        if eid:
            market_by_event.setdefault(eid, []).append(m)

    from scanner.core.event_store import EventRow
    pairs = []
    for eid, mkts in market_by_event.items():
        if eid in event_map:
            pairs.append((event_map[eid], mkts))
        else:
            total_vol = sum(m.volume or 0 for m in mkts)
            pairs.append((EventRow(
                event_id=eid, title=mkts[0].title if mkts else eid,
                volume=total_vol, updated_at="",
            ), mkts))

    with _timed_status(_console, "Filtering events"):
        ef_result = filter_events(pairs, min_volume=200_000)
    stage1_eids = ef_result.passed_event_ids
    logger.info("Stage 1 filter: %d events passed, %d rejected", len(stage1_eids), len(ef_result.rejected))

    # --- Stage 2: Quality gate (coarse — no depth data yet) ---
    from scanner.scan.event_scoring import compute_event_quality_score

    _MIN_EVENT_QUALITY = 55
    passed_eids: set[str] = set()
    for eid in stage1_eids:
        ev = event_map.get(eid)
        mkts = market_by_event.get(eid, [])
        if not ev or not mkts:
            continue
        eq_score = compute_event_quality_score(ev, mkts)
        if eq_score.total >= _MIN_EVENT_QUALITY:
            passed_eids.add(eid)

    # Collect only quality-gated markets
    eligible = [m for m in ef_result.passed_markets if getattr(m, "event_id", None) in passed_eids]
    _report("筛选", "done", f"{len(passed_eids)} 事件 / {len(eligible)} 市场 (从{len(stage1_eids)}事件筛选)")
    logger.info("Stage 2 quality gate: %d events (score >= %d)", len(passed_eids), _MIN_EVENT_QUALITY)

    # --- Fetch order books for quality-gated markets only ---
    if config.scanner.two_pass_scan and eligible:
        _report("获取盘口", "start")
        try:
            with _timed_status(_console, f"Fetching order books ({len(eligible)} markets)"):
                eligible = _run_async(enrich_with_orderbook(eligible, config))
            _report("获取盘口", "done", f"{len(eligible)} 市场")
        except Exception as e:
            _report("获取盘口", "fail")
            logger.warning("Order book fetch failed, continuing without depth data: %s", e)

    # Market type classification
    from scanner.scan.tag_classifier import classify_from_tags
    for market in eligible:
        market.market_type = classify_from_tags(market.tags)

    # Fetch crypto price data (deduped by asset)
    from scanner.market_types.registry import find_matching_module
    price_params: dict[str, dict] = {}
    if config.mispricing.enabled:
        _report("获取实时价格", "start")
        try:
            with _timed_status(_console, "Fetching price data"):
                price_params = _run_async(_fetch_price_params_batch(eligible, config))
            asset_prices: dict[str, float] = {}
            for params in price_params.values():
                label = params.pop("_asset_label", "?")
                p = params.get("current_underlying_price")
                if p:
                    asset_prices.setdefault(label, p)
            detail = " | ".join(f"{k}: ${v:,.0f}" for k, v in asset_prices.items())
            _report("获取实时价格", "done", detail or "无 crypto")
        except Exception as e:
            _report("获取实时价格", "skip")
            _console.print(" [dim]Price data skipped[/dim]")
            logger.warning("Price data fetch failed: %s", e)

    # Score ALL quality-gated markets (now with depth data)
    candidates: list[ScoredCandidate] = []
    for market in eligible:
        mkt_params = price_params.get(market.market_id, {})
        enrichment_mod = find_matching_module(market)
        if enrichment_mod and mkt_params:
            mispricing = enrichment_mod.detect_mispricing(market, mkt_params, config) or MispricingResult(signal="none")
        else:
            mispricing = detect_mispricing(market, config.mispricing)

        score = compute_structure_score(market, mispricing=mispricing)

        candidates.append(ScoredCandidate(
            market=market,
            score=score,
            mispricing=mispricing,
        ))

    # Tier classification (simplified: all passed = research)
    tiers = classify_tiers(candidates, config.scoring.thresholds)

    # Persist to DB: only quality-gated events + their markets
    if db is not None:
        _persist_filtered(eligible, markets, event_rows or [], db)
        _update_event_scores(candidates, db)
        _update_event_quality_scores(event_map, market_by_event, passed_eids, db)
        # Cleanup: close events where all active sub-markets have expired end_date
        from datetime import UTC, datetime
        now_iso = datetime.now(UTC).isoformat()
        db.conn.execute("""
            UPDATE events SET closed = 1
            WHERE closed = 0 AND event_id NOT IN (
                SELECT DISTINCT event_id FROM markets
                WHERE closed = 0 AND (end_date > ? OR end_date IS NULL)
            )
        """, (now_iso,))
        db.conn.commit()

    logger.info(
        "Tiers: A=%d, B=%d, C=%d",
        len(tiers.tier_a), len(tiers.tier_b), len(tiers.tier_c),
    )
    return tiers


def _persist_filtered(
    passed: list[Market],
    all_markets: list[Market],
    event_rows: list,
    db: PolilyDB,
) -> tuple[int, int]:
    """Persist only events with passing markets + all their sibling markets.

    If one sub-market of an event passes, ALL sibling markets of that event
    are persisted (for multi-outcome detail page completeness).

    Returns (n_events, n_markets) persisted.
    """
    from scanner.core.event_store import MarketRow, upsert_event, upsert_market

    # Find event_ids that have at least one passing market
    eligible_eids = {
        getattr(m, "event_id", None)
        for m in passed
        if getattr(m, "event_id", None)
    }

    if not eligible_eids:
        return 0, 0

    # Compute max end_date per event from sub-markets (API event.endDate can be wrong)
    event_max_end: dict[str, str] = {}
    for m in all_markets:
        eid = getattr(m, "event_id", None)
        if eid not in eligible_eids or not m.resolution_time:
            continue
        end_iso = m.resolution_time.isoformat()
        if eid not in event_max_end or end_iso > event_max_end[eid]:
            event_max_end[eid] = end_iso

    # Persist eligible events (with corrected end_date)
    n_events = 0
    for er in event_rows:
        if er.event_id in eligible_eids:
            if er.event_id in event_max_end:
                er.end_date = event_max_end[er.event_id]
            upsert_event(er, db)
            n_events += 1

    # Persist ALL markets belonging to eligible events (siblings included)
    # Expired sub-markets (end_date < now) are written but marked closed=1
    from datetime import UTC, datetime
    now = datetime.now(UTC)
    now_iso = now.isoformat()

    n_markets = 0
    for m in all_markets:
        eid = getattr(m, "event_id", None)
        if eid not in eligible_eids:
            continue

        # Check if this sub-market is expired
        is_expired = False
        if m.resolution_time and m.resolution_time < now:
            is_expired = True
        accepting = getattr(m, "accepting_orders", True)
        if not accepting:
            is_expired = True

        mr = MarketRow(
            market_id=m.market_id,
            event_id=eid,
            question=m.title,
            slug=getattr(m, "market_slug", None),
            description=m.description,
            group_item_title=getattr(m, "group_item_title", None),
            group_item_threshold=getattr(m, "group_item_threshold", None),
            condition_id=m.condition_id,
            question_id=getattr(m, "question_id", None),
            clob_token_id_yes=m.clob_token_id_yes,
            clob_token_id_no=m.clob_token_id_no,
            neg_risk=getattr(m, "neg_risk", False),
            neg_risk_request_id=getattr(m, "neg_risk_request_id", None),
            neg_risk_other=getattr(m, "neg_risk_other", False),
            resolution_source=m.resolution_source,
            end_date=m.resolution_time.isoformat() if m.resolution_time else None,
            volume=m.volume,
            yes_price=m.yes_price,
            no_price=m.no_price,
            best_bid=m.best_bid_yes,
            best_ask=m.best_ask_yes,
            spread=m.spread_yes,
            bid_depth=m.total_bid_depth_usd,
            ask_depth=m.total_ask_depth_usd,
            book_bids=json.dumps([{"price": b.price, "size": b.size} for b in m.book_depth_bids]) if m.book_depth_bids else None,
            book_asks=json.dumps([{"price": a.price, "size": a.size} for a in m.book_depth_asks]) if m.book_depth_asks else None,
            accepting_orders=0 if is_expired else (1 if accepting else 0),
            closed=1 if is_expired else 0,
            updated_at=now_iso,
        )
        upsert_market(mr, db)
        n_markets += 1

    db.conn.commit()
    return n_events, n_markets


def _update_event_scores(
    candidates: list[ScoredCandidate],
    db: PolilyDB,
) -> None:
    """Update markets.structure_score + score_breakdown in DB after scoring.

    Event-level score + tier are handled by _update_event_quality_scores.
    """
    # Update per-market scores + breakdown
    for c in candidates:
        eid = getattr(c.market, "event_id", None)
        if eid:
            bd = {
                "liquidity": round(c.score.liquidity_structure, 1),
                "verifiability": round(c.score.objective_verifiability, 1),
                "probability": round(c.score.probability_space, 1),
                "time": round(c.score.time_structure, 1),
                "friction": round(c.score.trading_friction, 1),
            }
            if c.score.net_edge > 0:
                bd["net_edge"] = round(c.score.net_edge, 1)
            breakdown = json.dumps(bd)
            db.conn.execute(
                "UPDATE markets SET structure_score = ?, score_breakdown = ? WHERE market_id = ?",
                (c.score.total, breakdown, c.market.market_id),
            )

    db.conn.commit()


def _update_event_quality_scores(
    event_map: dict,
    market_by_event: dict[str, list[Market]],
    passed_eids: set[str],
    db: PolilyDB,
) -> None:
    """Compute and store event-level quality scores (replaces max-of-sub-markets)."""
    from scanner.scan.event_scoring import compute_event_quality_score

    for eid in passed_eids:
        ev = event_map.get(eid)
        mkts = market_by_event.get(eid, [])
        if not ev or not mkts:
            continue
        score = compute_event_quality_score(ev, mkts)
        # Tier from event quality score (same thresholds as sub-market tiers)
        # All events that pass quality gate are "research" (no tier distinction)
        db.conn.execute(
            "UPDATE events SET structure_score = ?, tier = 'research' WHERE event_id = ?",
            (score.total, eid),
        )
    db.conn.commit()


async def enrich_with_orderbook(
    markets: list[Market],
    config: ScannerConfig,
) -> list[Market]:
    """Fetch order books for all markets concurrently from CLOB API.

    Uses asyncio.gather with Semaphore(100) for concurrent CLOB requests.
    Markets with fetch failures keep their existing depth (usually None).
    Stale books (bid≈0, ask≈1) are flagged by clearing depth to None.
    """
    import asyncio

    sem = asyncio.Semaphore(100)
    timeout = httpx.Timeout(config.api.request_timeout_seconds)

    async def _fetch_one(client: httpx.AsyncClient, market: Market) -> None:
        token_id = market.clob_token_id_yes
        if not token_id:
            return
        async with sem:
            try:
                resp = await client.get(
                    f"{CLOB_BASE}/book",
                    params={"token_id": token_id},
                )
                resp.raise_for_status()
                bids, asks = parse_clob_book(resp.json())

                if is_stale_book(bids, asks):
                    logger.warning("Stale book for %s, clearing depth", market.market_id)
                    market.book_depth_bids = None
                    market.book_depth_asks = None
                else:
                    market.book_depth_bids = bids
                    market.book_depth_asks = asks
            except Exception as e:
                logger.warning("Failed to fetch book for %s: %s", market.market_id, e)

    async with httpx.AsyncClient(timeout=timeout) as client:
        await asyncio.gather(*[_fetch_one(client, m) for m in markets])

    return markets


async def _fetch_price_params_batch(
    markets: list[Market], config: ScannerConfig,
) -> dict[str, dict]:
    """Fetch price params for crypto markets, deduped by asset.

    Groups markets by underlying asset (BTC, ETH, etc.), fetches price + vol
    once per asset, then builds params for each market using shared data.
    9 BTC markets → 2 API calls instead of 18.
    """
    from scanner.price_feeds import (
        BinancePriceFeed,
        compute_realized_vol,
        extract_crypto_asset,
        extract_threshold_price,
    )

    # Group markets by asset symbol
    asset_markets: dict[str, list[Market]] = {}
    for m in markets:
        symbol = extract_crypto_asset(m.title)
        if symbol and extract_threshold_price(m.title):
            asset_markets.setdefault(symbol, []).append(m)

    if not asset_markets:
        return {}

    # Fetch price + history once per unique asset (concurrent across assets)
    feed = BinancePriceFeed()
    vol_days = config.mispricing.crypto.volatility_lookback_days
    asset_data: dict[str, dict] = {}

    async def _fetch_asset(symbol: str) -> None:
        try:
            price = await feed.get_current_price(symbol)
            if price is None:
                return
            history = await feed.get_historical_prices(symbol, days=vol_days)
            vol = compute_realized_vol(history) if history else 0.60
            asset_data[symbol] = {
                "current_underlying_price": price,
                "annual_volatility": vol,
            }
        except Exception as e:
            logger.warning("Price fetch failed for %s: %s", symbol, e)

    await asyncio.gather(*[_fetch_asset(s) for s in asset_markets])
    await feed.close()

    # Build per-market params from shared asset data
    results: dict[str, dict] = {}
    for symbol, mkts in asset_markets.items():
        data = asset_data.get(symbol)
        if not data:
            continue
        asset_label = symbol.split("/")[0]  # "BTC/USDT" → "BTC"
        for m in mkts:
            threshold = extract_threshold_price(m.title)
            if threshold:
                results[m.market_id] = {
                    **data,
                    "threshold_price": threshold,
                    "_asset_label": asset_label,
                }

    return results


def _run_async(coro):
    """Run an async coroutine from sync code, handling nested event loops."""
    try:
        asyncio.get_running_loop()
        # Already in an event loop — run in a new thread with its own loop
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


    # AI functions removed — analysis is now on-demand via service.analyze_market()
