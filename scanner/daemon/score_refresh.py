"""Refresh market + event scores using live prices.

Called by global_poll after price update (Step 2).
Only recalculates price-sensitive dimensions; verifiability and time are stable.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    MarketRow,
    get_event,
    get_event_markets,
    market_row_to_model,
)
from scanner.price_feeds import extract_crypto_asset, extract_threshold_price
from scanner.scan.mispricing import MispricingResult, detect_mispricing
from scanner.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS, compute_structure_score

logger = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    markets_refreshed: int = 0
    events_refreshed: int = 0


def refresh_scores(
    db: PolilyDB,
    underlying_prices: dict[str, float],
    config=None,
) -> RefreshResult:
    """Recalculate scores for all markets that have a score_breakdown.

    1. Group scored markets by event
    2. For each market: rebuild Market model, recalc mispricing + score
    3. Merge fresh scores into existing breakdown (preserve verifiability/time)
    4. Recalculate event-level scores
    5. Batch commit
    """
    from scanner.scan.commentary import generate_commentary
    from scanner.scan.event_scoring import compute_event_quality_score

    if config is None:
        from scanner.core.config import ScannerConfig
        config = ScannerConfig()

    result = RefreshResult()
    now = datetime.now(UTC).isoformat()

    # Collect all scored markets grouped by event
    rows = db.conn.execute(
        """SELECT m.*, e.market_type
        FROM markets m JOIN events e ON m.event_id = e.event_id
        WHERE m.active = 1 AND m.closed = 0
        AND m.score_breakdown IS NOT NULL
        AND e.closed = 0""",
    ).fetchall()

    if not rows:
        return result

    # Group by event_id
    by_event: dict[str, list] = {}
    for row in rows:
        eid = row["event_id"]
        by_event.setdefault(eid, []).append(row)

    # Map ccxt pair → Binance symbol for underlying lookup
    # e.g. "BTC/USDT" → underlying_prices["BTCUSDT"]
    def _get_underlying(event_title: str) -> float | None:
        pair = extract_crypto_asset(event_title)
        if not pair:
            return None
        sym = pair.replace("/", "")
        return underlying_prices.get(sym)

    for event_id, market_rows in by_event.items():
        try:
            event = get_event(event_id, db)
            if not event:
                continue

            market_type = event.market_type or "other"
            tw = _TYPE_WEIGHTS.get(market_type, _DEFAULT_WEIGHTS)
            underlying = _get_underlying(event.title)

            # Build Market models for event-level scoring
            market_models = []

            for mrow in market_rows:
                mr = MarketRow.model_validate(dict(mrow))
                market = market_row_to_model(mr, market_type=market_type)
                market_models.append(market)

                old_bd = json.loads(mr.score_breakdown)

                # Recalculate mispricing (crypto only)
                mispricing = MispricingResult(signal="none")
                if market_type in ("crypto", "crypto_threshold") and underlying is not None:
                    old_pp = old_bd.get("price_params", {})
                    threshold = old_pp.get("threshold_price") or extract_threshold_price(mr.question)
                    vol = old_pp.get("annual_volatility")
                    if threshold and vol:
                        mispricing = detect_mispricing(
                            market, config.mispricing,
                            current_underlying_price=underlying,
                            threshold_price=threshold,
                            annual_volatility=vol,
                        )

                # Recalculate structure score
                score = compute_structure_score(market, mispricing=mispricing)

                # Merge into existing breakdown (preserve verifiability, time, commentary structure)
                new_bd = dict(old_bd)
                new_bd["liquidity"] = round(score.liquidity_structure, 1)
                new_bd["probability"] = round(score.probability_space, 1)
                new_bd["friction"] = round(score.trading_friction, 1)
                if tw.get("net_edge", 0) > 0:
                    new_bd["net_edge"] = round(score.net_edge, 1)

                # Update mispricing data
                if mispricing.theoretical_fair_value is not None or mispricing.signal != "none":
                    new_bd["mispricing"] = {
                        "fair_value": mispricing.theoretical_fair_value,
                        "fair_value_low": mispricing.fair_value_low,
                        "fair_value_high": mispricing.fair_value_high,
                        "deviation_pct": mispricing.deviation_pct,
                        "direction": mispricing.direction,
                        "signal": mispricing.signal,
                        "model_confidence": mispricing.model_confidence,
                    }
                if underlying is not None and "price_params" in new_bd:
                    new_bd["price_params"]["underlying_price"] = underlying

                # Round-trip friction
                if market.round_trip_friction_pct is not None:
                    new_bd["round_trip_friction_pct"] = round(market.round_trip_friction_pct, 4)

                # Refresh commentary
                commentary = generate_commentary(
                    new_bd, score.total, mr.market_id, market_type=market_type,
                )
                new_bd["commentary"] = commentary

                db.conn.execute(
                    "UPDATE markets SET structure_score = ?, score_breakdown = ?, updated_at = ? WHERE market_id = ?",
                    (score.total, json.dumps(new_bd, ensure_ascii=False, default=str), now, mr.market_id),
                )
                result.markets_refreshed += 1

            # Recalculate event-level score
            if market_models:
                event_score = compute_event_quality_score(event, market_models)
                db.conn.execute(
                    "UPDATE events SET structure_score = ?, updated_at = ? WHERE event_id = ?",
                    (event_score.total, now, event_id),
                )
                result.events_refreshed += 1

        except Exception:
            logger.exception("Score refresh failed for event %s", event_id)
            continue

    db.conn.commit()

    if result.markets_refreshed > 0:
        logger.debug(
            "Refreshed %d markets, %d events",
            result.markets_refreshed, result.events_refreshed,
        )

    return result
