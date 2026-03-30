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
from scanner.market_classifier import classify_market_type
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
    _report("过滤市场", "done", f"{len(filter_result.passed)} 通过")
    logger.info(
        "Filters: %d passed, %d rejected out of %d",
        len(filter_result.passed), len(filter_result.rejected), len(markets),
    )

    passed = filter_result.passed

    # Two-pass: fetch order books for top candidates
    if config.scanner.two_pass_scan and passed:
        top_n = config.scanner.orderbook_fetch_top_n
        _report("获取订单簿", "start")
        try:
            with _timed_status(_console, f"Fetching order books (top {top_n})"):
                passed = _run_async(enrich_with_orderbook(passed, config))
            _report("获取订单簿", "done", f"前 {top_n} 个")
            logger.info("Order books fetched for top %d markets", top_n)
        except Exception as e:
            _report("获取订单簿", "fail")
            logger.warning("Order book fetch failed, continuing without depth data: %s", e)

    # Phase 9: Market type classification (rule-based for all, AI for top N only)
    for market in passed:
        market.market_type = classify_market_type(market, config.market_types)

    # Pre-score all markets with rules first (fast) to identify top candidates for AI
    ai_enrichments = {}
    if config.ai.enabled and config.ai.market_analyst.enabled and passed:
        # Pre-score with rules to rank markets, then only AI-analyze top N.
        # Note: pre-score lacks AI objectivity, so ranking may differ slightly
        # from final score. This is an intentional tradeoff for 10x speed.
        pre_scores = sorted(
            ((compute_beauty_score(m, config.scoring.weights, config.filters).total, m) for m in passed),
            key=lambda x: x[0], reverse=True,
        )
        ai_top_n = min(config.ai.market_analyst.max_candidates or 15, len(pre_scores))
        ai_candidates = [m for _, m in pre_scores[:ai_top_n]]

        _report(f"AI 分析 {ai_top_n} 个市场", "start")
        try:
            with _timed_status(_console, f"AI analyzing top {ai_top_n} markets"):
                ai_enrichments = _run_async(_run_market_analyst(ai_candidates, config))
            _report(f"AI 分析 {ai_top_n} 个市场", "done")
        except Exception as e:
            _report(f"AI 分析 {ai_top_n} 个市场", "fail")
            _console.print(" [yellow]AI fallback to rules[/yellow]")
            logger.warning("AI MarketAnalyst failed: %s", e)

    # Apply AI enrichments where available
    for market in passed:
        enrichment = ai_enrichments.get(market.market_id)
        if enrichment:
            market.market_type = enrichment.market_type

    # Fetch price params via plugins for mispricing detection
    price_params: dict[str, dict] = {}
    if config.mispricing.enabled:
        _report("获取价格数据", "start")
        try:
            with _timed_status(_console, "Fetching price data (plugins)"):
                price_params = _run_async(_fetch_price_params_batch(passed, config))
            _report("获取价格数据", "done")
        except Exception as e:
            _report("获取价格数据", "skip")
            _console.print(" [dim]Price data skipped[/dim]")
            logger.warning("Price data fetch failed: %s", e)

    # Phase 6 + 6b: Score + Mispricing
    _report("评分 + 定价分析", "start")
    candidates: list[ScoredCandidate] = []
    for market in passed:
        type_config = config.market_types.get(market.market_type or "")
        overrides = type_config.scoring_overrides if type_config else None

        enrichment = ai_enrichments.get(market.market_id)
        ai_objectivity = enrichment.objectivity_score if enrichment else None

        score = compute_beauty_score(
            market,
            config.scoring.weights,
            config.filters,
            weight_overrides=overrides,
            objectivity_score=ai_objectivity,
            probability_penalty_mode=config.scoring.thresholds.probability_penalty_mode,
        )

        # Try plugin mispricing first, fall through to generic
        mispricing_kwargs = price_params.get(market.market_id, {})
        mispricing = _detect_mispricing_with_plugin(market, mispricing_kwargs, config)

        candidates.append(ScoredCandidate(
            market=market,
            score=score,
            mispricing=mispricing,
        ))

    # Tier classification
    tiers = classify_tiers(candidates, config.scoring.thresholds)
    _report("评分 + 定价分析", "done", f"{len(candidates)} 个市场")

    # Agent 2: Narrative generation for top candidates only (max 5)
    if config.ai.enabled and config.ai.narrative_writer.enabled:
        max_narratives = config.ai.narrative_writer.max_candidates or 8
        top_candidates = (tiers.tier_a + tiers.tier_b)[:max_narratives]
        if top_candidates:
            # Build per-candidate context from previous analyses
            narrative_contexts = _build_narrative_contexts(
                top_candidates, config.archiving.analyses_file,
            )
            _report(f"AI 撰写叙述 ({len(top_candidates)} 个)", "start")
            try:
                with _timed_status(_console, f"AI writing narratives ({len(top_candidates)} candidates)"):
                    narratives = _run_async(_run_narrative_writer(
                        top_candidates, config, contexts=narrative_contexts,
                    ))
                _attach_narratives(tiers, narratives)
                _report(f"AI 撰写叙述 ({len(top_candidates)} 个)", "done")
            except Exception as e:
                _report(f"AI 撰写叙述 ({len(top_candidates)} 个)", "fail")
                _console.print(" [dim]Narratives skipped[/dim]")
                logger.warning("AI NarrativeWriter failed: %s", e)

    logger.info(
        "Tiers: A=%d, B=%d, C=%d",
        len(tiers.tier_a), len(tiers.tier_b), len(tiers.tier_c),
    )
    return tiers


async def enrich_with_orderbook(
    markets: list[Market],
    config: ScannerConfig,
) -> list[Market]:
    """Fetch order books for top N markets from CLOB API.

    Markets beyond top_n or with fetch failures keep their existing depth (usually None).
    Stale books (bid≈0, ask≈1) are flagged by clearing depth to None.
    """
    top_n = config.scanner.orderbook_fetch_top_n
    to_fetch = markets[:top_n]
    rest = markets[top_n:]

    client = PolymarketClient(config.api)
    try:
        for market in to_fetch:
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

    return to_fetch + rest


async def _fetch_price_params_batch(
    markets: list[Market], config: ScannerConfig,
) -> dict[str, dict]:
    """Fetch price params for markets via plugins. Returns {market_id: params}."""
    from scanner.market_types.registry import discover_plugins

    plugins = discover_plugins()
    results = {}
    for market in markets:
        plugin = plugins.get(market.market_type or "")
        if plugin is None or not hasattr(plugin, "fetch_price_params"):
            continue
        try:
            params = await plugin.fetch_price_params(market, config)
            if params:
                results[market.market_id] = params
        except Exception as e:
            logger.warning("Price fetch failed for %s (%s): %s", market.market_id, market.market_type, e)
    return results


def _detect_mispricing_with_plugin(
    market: Market, price_params: dict, config: ScannerConfig,
) -> MispricingResult:
    """Try plugin mispricing detection, fall through to generic."""
    from scanner.market_types.registry import get_plugin

    plugin = get_plugin(market.market_type or "")
    if plugin and hasattr(plugin, "detect_mispricing") and price_params:
        try:
            result = plugin.detect_mispricing(market, price_params, config)
            if result is not None:
                return result
        except Exception as e:
            logger.warning("Plugin mispricing failed for %s: %s", market.market_id, e)

    return detect_mispricing(market, config.mispricing, **price_params)


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
    results = await agent.generate_batch(candidates, contexts=contexts)

    return {r.market_id: r for r in results}


def _attach_narratives(tiers: TierResult, narratives: dict):
    """Attach AI-generated narratives to candidates (stored as metadata)."""
    for c in tiers.tier_a + tiers.tier_b:
        narrative = narratives.get(c.market.market_id)
        if narrative:
            c.narrative = narrative
