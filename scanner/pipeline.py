"""Core scan pipeline: fetch → filter → classify → score → mispricing → [AI] → tier."""

import asyncio
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from scanner.api import PolymarketClient
from scanner.config import ScannerConfig
from scanner.filters import apply_hard_filters
from scanner.mispricing import MispricingResult, detect_mispricing
from scanner.models import Market
from scanner.orderbook import is_stale_book
from scanner.reporting import ScoredCandidate, TierResult, classify_tiers
from scanner.scoring import compute_beauty_score

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
    _report("过滤市场", "start")
    with _timed_status(_console, "Filtering markets"):
        filter_result = apply_hard_filters(markets, config.filters, config.heuristics)
    total = len(markets)
    passed_n = len(filter_result.passed)
    rejected_n = len(filter_result.rejected)
    _report("过滤市场", "done", f"{passed_n}/{total} 通过 ({rejected_n} 过滤)")
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
            _report("获取订单簿", "done", f"{len(passed)} 个市场")
            logger.info("Order books fetched for %d markets", len(passed))
        except Exception as e:
            _report("获取订单簿", "fail")
            logger.warning("Order book fetch failed, continuing without depth data: %s", e)

    # Market type classification from Polymarket tags
    from scanner.tag_classifier import classify_from_tags
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
        type_config = config.market_types.get(market.market_type or "")
        overrides = type_config.scoring_overrides if type_config else None

        score = compute_beauty_score(
            market,
            config.scoring.weights,
            config.filters,
            weight_overrides=overrides,
            probability_penalty_mode=config.scoring.thresholds.probability_penalty_mode,
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
    _report("评分 + 定价检测", "done", f"研{research_n} 观{watch_n} (共{len(candidates)})")

    # AI analysis removed from scan pipeline — triggered on-demand via 'a' key

    logger.info(
        "Tiers: A=%d, B=%d, C=%d",
        len(tiers.tier_a), len(tiers.tier_b), len(tiers.tier_c),
    )
    return tiers


async def enrich_with_orderbook(
    markets: list[Market],
    config: ScannerConfig,
) -> list[Market]:
    """Fetch order books for all passed markets from CLOB API.

    Markets with fetch failures keep their existing depth (usually None).
    Stale books (bid≈0, ask≈1) are flagged by clearing depth to None.
    """
    client = PolymarketClient(config.api)
    try:
        for market in markets:
            try:
                token_id = market.clob_token_id_yes
                if not token_id:
                    continue
                bids, asks = await client.fetch_book(token_id)

                if is_stale_book(bids, asks):
                    logger.warning("Stale book for %s, clearing depth", market.market_id)
                    market.book_depth_bids = None
                    market.book_depth_asks = None
                else:
                    market.book_depth_bids = bids
                    market.book_depth_asks = asks
            except Exception as e:
                logger.warning("Failed to fetch book for %s: %s", market.market_id, e)
    finally:
        await client.close()

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


async def _run_market_analyst(
    markets: list[Market], config: ScannerConfig,
) -> dict:
    """Run Agent 1 (MarketAnalyst) on filtered markets."""
    from scanner.agents.market_analyst import MarketAnalystAgent

    agent = MarketAnalystAgent(config.ai.market_analyst, config.heuristics)
    results = await agent.analyze_batch(markets)

    return {r.market_id: r for r in results}


def _build_narrative_contexts(
    candidates: list[ScoredCandidate], analyses_file: str,
) -> dict[str, str]:
    """Build per-candidate context from previous analyses. Single file read."""
    from scanner.analysis_store import AnalysisVersion, build_previous_context, load_analyses

    all_data = load_analyses(analyses_file)
    contexts = {}
    for c in candidates:
        raw_list = all_data.get(c.market.market_id, [])
        if not raw_list:
            continue
        try:
            existing = [AnalysisVersion.model_validate(v) for v in raw_list]
        except Exception:
            continue
        ctx = build_previous_context(existing)
        if ctx:
            contexts[c.market.market_id] = ctx
    return contexts


async def _run_narrative_writer(
    candidates: list[ScoredCandidate], config: ScannerConfig,
    contexts: dict[str, str] | None = None,
) -> dict:
    """Run Agent 2 (NarrativeWriter) on top candidates."""
    from scanner.agents.narrative_writer import NarrativeWriterAgent

    agent = NarrativeWriterAgent(config.ai.narrative_writer)
    include_bias = config.execution_hints.show_conditional_advice
    results = await agent.generate_batch(candidates, contexts=contexts, include_bias=include_bias)

    return {r.market_id: r for r in results}


def _attach_narratives(tiers: TierResult, narratives: dict):
    """Attach AI-generated narratives to candidates (stored as metadata)."""
    for c in tiers.tier_a + tiers.tier_b:
        narrative = narratives.get(c.market.market_id)
        if narrative:
            c.narrative = narrative
