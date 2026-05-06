"""Pipeline: single-event fetch + score + persist, orderbook enrichment, price params."""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import httpx

from polily.core.config import PolilyConfig
from polily.core.models import BookLevel, Market
from polily.scan.mispricing import MispricingResult, detect_mispricing
from polily.scan.reporting import ScoredCandidate
from polily.scan.scoring import compute_structure_score

if TYPE_CHECKING:
    from polily.core.db import PolilyDB

logger = logging.getLogger(__name__)


def _update_event_scores(
    candidates: list[ScoredCandidate],
    db: PolilyDB,
    price_params: dict | None = None,
) -> None:
    """Update markets.structure_score + score_breakdown in DB after scoring.

    Event-level score + tier are handled by _update_event_quality_scores.
    """
    price_params = price_params or {}
    # Update per-market scores + breakdown.
    #
    # v0.11.5: commentary text is NO LONGER persisted into score_breakdown.
    # Pre-v0.11.5 we baked the zh/en strings into the JSON at scoring
    # time, which made F2 toggle leave commentary in stale language.
    # Now the view layer re-renders commentary on every paint via
    # `polily.tui.commentary_render.render_commentary` using
    # `current_language()` — same pattern as Yuan's i18n labels.
    # Numeric breakdown still persists (drives the bars + agent prompts).

    with db.transaction() as conn:
        for c in candidates:
            eid = getattr(c.market, "event_id", None)
            if eid:
                from polily.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS
                mtype = getattr(c.market, "market_type", "other")
                _tw = _TYPE_WEIGHTS.get(mtype, _DEFAULT_WEIGHTS)
                bd = {
                    "liquidity": round(c.score.liquidity_structure, 1),
                    "verifiability": round(c.score.objective_verifiability, 1),
                    "probability": round(c.score.probability_space, 1),
                    "time": round(c.score.time_structure, 1),
                    "friction": round(c.score.trading_friction, 1),
                }
                if _tw.get("net_edge", 0) > 0:
                    bd["net_edge"] = round(c.score.net_edge, 1)
                # Persist mispricing data for agent consumption
                mp = c.mispricing
                if mp.signal != "none" or mp.theoretical_fair_value is not None:
                    bd["mispricing"] = {
                        "fair_value": mp.theoretical_fair_value,
                        "fair_value_low": mp.fair_value_low,
                        "fair_value_high": mp.fair_value_high,
                        "deviation_pct": mp.deviation_pct,
                        "direction": mp.direction,
                        "signal": mp.signal,
                        "model_confidence": mp.model_confidence,
                    }
                # Persist price params (volatility, threshold, underlying price)
                mkt_p = price_params.get(c.market.market_id, {})
                if mkt_p:
                    bd["price_params"] = {
                        k: v for k, v in {
                            "underlying_price": mkt_p.get("current_underlying_price"),
                            "threshold_price": mkt_p.get("threshold_price"),
                            "annual_volatility": mkt_p.get("annual_volatility"),
                            "vol_source": mkt_p.get("vol_source"),
                        }.items() if v is not None
                    }
                # Round-trip friction
                if c.market.round_trip_friction_pct is not None:
                    bd["round_trip_friction_pct"] = round(c.market.round_trip_friction_pct, 4)
                # v0.11.5: bd no longer includes "commentary" — view layer
                # generates it live in current language on each render.
                breakdown = json.dumps(bd)
                conn.execute(
                    "UPDATE markets SET structure_score = ?, score_breakdown = ? WHERE market_id = ?",
                    (c.score.total, breakdown, c.market.market_id),
                )


async def enrich_with_orderbook(
    markets: list[Market],
    config: PolilyConfig,
) -> list[Market]:
    """Fetch order books + real bid/ask for all markets from CLOB API.

    Uses fetch_clob_market_data (4 endpoints per market) to get accurate
    bid/ask from /price endpoints (not /book, which is unreliable for negRisk).
    Markets with fetch failures keep their existing data (usually None).
    """
    import asyncio

    from polily.core.clob import fetch_clob_market_data

    sem = asyncio.Semaphore(100)
    timeout = httpx.Timeout(config.api.request_timeout_seconds)

    async def _fetch_one(client: httpx.AsyncClient, market: Market) -> None:
        token_id = market.clob_token_id_yes
        if not token_id:
            return
        async with sem:
            try:
                data = await fetch_clob_market_data(client, token_id)

                # Book depth
                if data.get("book_bids"):
                    raw_bids = json.loads(data["book_bids"])
                    market.book_depth_bids = [
                        BookLevel(price=b["price"], size=b["size"]) for b in raw_bids
                    ]
                if data.get("book_asks"):
                    raw_asks = json.loads(data["book_asks"])
                    market.book_depth_asks = [
                        BookLevel(price=a["price"], size=a["size"]) for a in raw_asks
                    ]

                # Real bid/ask from /price endpoints
                if data.get("best_bid") is not None:
                    market.best_bid_yes = data["best_bid"]
                if data.get("best_ask") is not None:
                    market.best_ask_yes = data["best_ask"]
                if data.get("spread") is not None:
                    market.spread_yes = data["spread"]

            except Exception as e:
                logger.warning("Failed to fetch book for %s: %s", market.market_id, e)

    async with httpx.AsyncClient(timeout=timeout) as client:
        await asyncio.gather(*[_fetch_one(client, m) for m in markets])

    return markets


async def _fetch_price_params_batch(
    markets: list[Market], config: PolilyConfig,
) -> dict[str, dict]:
    """Fetch price params for crypto markets, deduped by asset.

    Groups markets by underlying asset (BTC, ETH, etc.), fetches price + vol
    once per asset, then builds params for each market using shared data.
    9 BTC markets → 2 API calls instead of 18.
    """
    from polily.price_feeds import (
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
                "vol_source": "binance" if history else "fallback_default",
                "vol_data_days": len(history),
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
        for m in mkts:
            threshold = extract_threshold_price(m.title)
            if threshold:
                results[m.market_id] = {
                    **data,
                    "threshold_price": threshold,
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


# ---------------------------------------------------------------------------
# Single-event flow
# ---------------------------------------------------------------------------


async def _fetch_event_by_slug(slug: str, config: PolilyConfig) -> dict | None:
    """Fetch single event from Gamma API by slug."""
    from polily.api import PolymarketClient

    client = PolymarketClient(config.api)
    try:
        return await client.fetch_event_by_slug(slug)
    finally:
        await client.close()


async def fetch_and_score_event(
    slug: str,
    *,
    config: PolilyConfig,
    db: PolilyDB,
    progress_cb=None,
) -> dict | None:
    """Single-event flow: fetch by slug -> enrich -> score -> persist.

    Returns {event, markets, scored_markets, event_score} or None if not found.
    """
    from polily.api import parse_gamma_event
    from polily.scan.event_scoring import compute_event_quality_score

    # v0.11.5 i18n: pipeline emits stable catalog keys (+ optional
    # detail_params dict) through progress_cb. The TUI side renders
    # `t(name_key, **params)` at paint time — F2 toggle re-translates
    # both live progress AND persisted scan_logs records on the next
    # render. Keeps `polily.scan` framework-free of `polily.tui.i18n`.
    def _report(
        name_key: str,
        status: str,
        detail_key: str | None = None,
        detail_params: dict | None = None,
    ):
        if progress_cb:
            progress_cb(name_key, status, detail_key, detail_params)

    # 1. Fetch from Gamma API
    _report("pipeline.step.fetch_event", "start")
    event_data = await _fetch_event_by_slug(slug, config)
    if not event_data:
        _report(
            "pipeline.step.fetch_event", "fail",
            detail_key="pipeline.detail.event_not_found",
        )
        return None
    event_row, markets = parse_gamma_event(event_data)
    _report(
        "pipeline.step.fetch_event", "done",
        detail_key="pipeline.detail.event_summary",
        detail_params={"title": event_row.title, "count": len(markets)},
    )

    if not markets:
        return None

    # 2. Fetch orderbook
    _report("pipeline.step.fetch_orderbook", "start")
    markets = await enrich_with_orderbook(markets, config)
    _report(
        "pipeline.step.fetch_orderbook", "done",
        detail_key="pipeline.detail.market_count",
        detail_params={"count": len(markets)},
    )

    # 3. Fetch Binance prices (crypto only)
    price_params: dict = {}
    if event_row.market_type in ("crypto", "crypto_threshold"):
        _report("pipeline.step.fetch_prices", "start")
        price_params = await _fetch_price_params_batch(markets, config)
        _report("pipeline.step.fetch_prices", "done")

    # 4. Score each market
    _report("pipeline.step.scoring", "start")
    scored = []
    for m in markets:
        m.market_type = event_row.market_type
        mp = price_params.get(m.market_id, {})
        mispricing = detect_mispricing(m, config.mispricing, **mp) if mp else MispricingResult(signal="none")
        score = compute_structure_score(m, mispricing=mispricing)
        scored.append(ScoredCandidate(market=m, score=score, mispricing=mispricing))

    # 5. Event quality score
    event_score = compute_event_quality_score(event_row, markets)
    _report(
        "pipeline.step.scoring", "done",
        detail_key="pipeline.detail.event_score",
        detail_params={"score": event_score.total},
    )

    # 6. Persist to DB
    _persist_single_event(event_row, markets, scored, event_score, price_params, db)

    return {
        "event": event_row,
        "markets": markets,
        "scored_markets": scored,
        "event_score": event_score,
    }


def _persist_single_event(event_row, markets, scored, event_score, price_params, db):
    """Persist a single event + markets + scores to DB."""
    from datetime import UTC, datetime

    from polily.core.event_store import market_model_to_row, upsert_event, upsert_market

    upsert_event(event_row, db)
    for m in markets:
        row = market_model_to_row(m, event_row.event_id)
        upsert_market(row, db)

    _update_event_scores(scored, db, price_params=price_params)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE events SET structure_score = ?, updated_at = ? WHERE event_id = ?",
            (event_score.total, datetime.now(UTC).isoformat(), event_row.event_id),
        )
