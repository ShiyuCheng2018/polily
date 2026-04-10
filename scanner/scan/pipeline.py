"""Core scan pipeline: fetch → filter → classify → score → mispricing → [AI] → tier."""

from __future__ import annotations

import asyncio
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
from scanner.scan.filters import apply_hard_filters
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
    _report("过滤", "start")
    with _timed_status(_console, "Filtering markets"):
        filter_result = apply_hard_filters(markets, config.filters, config.heuristics)
    passed_n = len(filter_result.passed)
    passed_eids = {getattr(m, "event_id", None) for m in filter_result.passed if getattr(m, "event_id", None)}
    total_eids = {getattr(m, "event_id", None) for m in markets if getattr(m, "event_id", None)}
    _report("过滤", "done", f"{len(passed_eids)} 事件 / {passed_n} 市场通过 ({len(total_eids) - len(passed_eids)} 事件过滤)")
    logger.info(
        "Filters: %d passed, %d rejected out of %d",
        len(filter_result.passed), len(filter_result.rejected), len(markets),
    )

    passed = filter_result.passed

    # Fetch order books for all passed markets
    if config.scanner.two_pass_scan and passed:
        _report("获取订单簿", "start")
        try:
            with _timed_status(_console, f"Fetching order books ({len(passed)} markets)"):
                passed = _run_async(enrich_with_orderbook(passed, config))
            _report("获取订单簿", "done", f"{len(passed)} 市场")
            logger.info("Order books fetched for %d markets", len(passed))
        except Exception as e:
            _report("获取订单簿", "fail")
            logger.warning("Order book fetch failed, continuing without depth data: %s", e)

    # Market type classification from Polymarket tags
    from scanner.scan.tag_classifier import classify_from_tags
    for market in passed:
        market.market_type = classify_from_tags(market.tags)

    # Fetch price data via data enrichment modules
    from scanner.market_types.registry import find_matching_module
    price_params: dict[str, dict] = {}
    if config.mispricing.enabled:
        _report("获取实时价格 (Binance)", "start")
        try:
            with _timed_status(_console, "Fetching price data"):
                price_params = _run_async(_fetch_price_params_batch(passed, config))
            # Build detail: show assets and prices
            price_details = []
            for _mid, params in list(price_params.items())[:3]:
                p = params.get("current_underlying_price")
                if p:
                    price_details.append(f"${p:,.0f}")
            detail = f"{len(price_params)} 个 crypto" + (f" ({', '.join(price_details)})" if price_details else "")
            _report("获取实时价格 (Binance)", "done", detail)
        except Exception as e:
            _report("获取实时价格 (Binance)", "skip")
            _console.print(" [dim]Price data skipped[/dim]")
            logger.warning("Price data fetch failed: %s", e)

    # Score + Mispricing (pure rules, no AI)
    _report("评分 + 定价检测", "start")
    candidates: list[ScoredCandidate] = []
    for market in passed:
        score = compute_structure_score(
            market,
            config.scoring.weights,
        )

        # Try enrichment module mispricing, fall through to generic
        mkt_params = price_params.get(market.market_id, {})
        enrichment_mod = find_matching_module(market)
        if enrichment_mod and mkt_params:
            mispricing = enrichment_mod.detect_mispricing(market, mkt_params, config) or MispricingResult(signal="none")
        else:
            mispricing = detect_mispricing(market, config.mispricing)

        candidates.append(ScoredCandidate(
            market=market,
            score=score,
            mispricing=mispricing,
        ))

    # Tier classification
    tiers = classify_tiers(candidates, config.scoring.thresholds)
    research_n = len(tiers.tier_a)
    watch_n = len(tiers.tier_b)
    scored_eids = {getattr(c.market, "event_id", None) for c in candidates if getattr(c.market, "event_id", None)}
    _report("评分 + 定价检测", "done", f"研{research_n} 观{watch_n} (共{len(scored_eids)}事件/{len(candidates)}市场)")

    # AI analysis removed from scan pipeline — triggered on-demand via 'a' key

    # Persist to DB: only filtered events + all their sibling markets, then scores
    if db is not None:
        _report("持久化", "start")
        n_events, n_markets = _persist_filtered(passed, markets, event_rows or [], db)
        _report("持久化", "done", f"{n_events} 事件 / {n_markets} 市场写入 DB")
        _update_event_scores(candidates, tiers, db)

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

    # Persist eligible events
    n_events = 0
    for er in event_rows:
        if er.event_id in eligible_eids:
            upsert_event(er, db)
            n_events += 1

    # Persist ALL markets belonging to eligible events (siblings included)
    n_markets = 0
    for m in all_markets:
        eid = getattr(m, "event_id", None)
        if eid not in eligible_eids:
            continue
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
            accepting_orders=getattr(m, "accepting_orders", True),
            updated_at=__import__("datetime").datetime.now(
                __import__("datetime").UTC
            ).isoformat(),
        )
        upsert_market(mr, db)
        n_markets += 1

    db.conn.commit()
    return n_events, n_markets


def _update_event_scores(
    candidates: list[ScoredCandidate],
    tiers: TierResult,
    db: PolilyDB,
) -> None:
    """Update events.structure_score/tier and markets.structure_score in DB after scoring."""
    # Build event_id → max score mapping (event gets its best market's score)
    event_scores: dict[str, float] = {}
    for c in candidates:
        eid = getattr(c.market, "event_id", None)
        if eid:
            current = event_scores.get(eid, 0.0)
            event_scores[eid] = max(current, c.score.total)

    # Build event_id → best tier mapping (research > watchlist > filtered)
    event_tiers: dict[str, str] = {}
    for c in tiers.tier_a:
        eid = getattr(c.market, "event_id", None)
        if eid:
            event_tiers[eid] = "research"
    for c in tiers.tier_b:
        eid = getattr(c.market, "event_id", None)
        if eid and eid not in event_tiers:
            event_tiers[eid] = "watchlist"
    for c in tiers.tier_c:
        eid = getattr(c.market, "event_id", None)
        if eid and eid not in event_tiers:
            event_tiers[eid] = "filtered"

    # Update event rows
    for eid, score in event_scores.items():
        tier = event_tiers.get(eid, "filtered")
        db.conn.execute(
            "UPDATE events SET structure_score = ?, tier = ? WHERE event_id = ?",
            (score, tier, eid),
        )

    # Update per-market scores
    for c in candidates:
        eid = getattr(c.market, "event_id", None)
        if eid:
            db.conn.execute(
                "UPDATE markets SET structure_score = ? WHERE market_id = ?",
                (c.score.total, c.market.market_id),
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
    """Fetch price params for markets via data enrichment modules."""
    from scanner.market_types.registry import find_matching_module

    results = {}
    for market in markets:
        enrichment = find_matching_module(market)
        if enrichment is None:
            continue
        try:
            params = await enrichment.fetch_price_params(market, config)
            if params:
                results[market.market_id] = params
        except Exception as e:
            logger.warning("Price fetch failed for %s: %s", market.market_id, e)
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
