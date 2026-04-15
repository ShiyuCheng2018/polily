"""Event-level quality scoring — 6 dimensions.

Determines if an event is worth researching. Uses event-level aggregates
plus best sub-market tradability.

Dimensions (total 100):
  1. Information Value (20)       — entropy, leader margin
  2. Liquidity Aggregate (20)     — volume, min depth, coverage ratio
  3. Resolution Quality (15)      — resolution source, description quality
  4. Consistency (10)             — overround, pricing efficiency
  5. Time Window (20)             — 1-7 days sweet spot, steep decay beyond
  6. Best Market Quality (15)     — best sub-market structure score
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.event_store import EventRow
    from scanner.core.models import Market


@dataclass
class EventQualityScore:
    """Event-level quality score with 6 dimensions."""

    information_value: float = 0.0       # 0-20
    liquidity_aggregate: float = 0.0     # 0-20
    resolution_quality: float = 0.0      # 0-15
    consistency: float = 0.0             # 0-10
    time_window: float = 0.0             # 0-20
    best_market_quality: float = 0.0     # 0-15
    total: float = 0.0                   # 0-100


def compute_event_quality_score(
    event: EventRow,
    markets: list[Market],
) -> EventQualityScore:
    """Compute event-level quality score from event + sub-market data."""
    active = [m for m in markets if m.yes_price and m.yes_price > 0]
    if not active:
        return EventQualityScore()

    neg_risk = getattr(event, "neg_risk", False)
    info = _score_information_value(active, neg_risk=neg_risk)
    liq = _score_liquidity_aggregate(event, active)
    res = _score_resolution_quality(event)
    con = _score_consistency(active, neg_risk=neg_risk)
    time = _score_time_window(active)
    bmq = _score_best_market_quality(active)

    return EventQualityScore(
        information_value=info,
        liquidity_aggregate=liq,
        resolution_quality=res,
        consistency=con,
        time_window=time,
        best_market_quality=bmq,
        total=round(info + liq + res + con + time + bmq, 2),
    )


# ---------------------------------------------------------------------------
# Dimension 1: Information Value (0-20)
# ---------------------------------------------------------------------------

def _score_information_value(markets: list[Market], *, neg_risk: bool = False) -> float:
    """How uncertain/interesting is this event.

    negRisk (mutually exclusive): entropy + leader margin.
    Non-negRisk (independent): tradeable market ratio + best probability space.
    """
    prices = [m.yes_price for m in markets if m.yes_price and m.yes_price > 0]
    if not prices:
        return 0.0

    if neg_risk:
        return _info_neg_risk(prices)
    return _info_independent(prices)


def _info_neg_risk(prices: list[float]) -> float:
    """negRisk: entropy + leader margin (original logic)."""
    total = sum(prices)
    if total <= 0:
        return 0.0

    n = len(prices)

    # Normalized Shannon entropy (0-1, higher = more uncertain = more interesting)
    if n > 1:
        probs = [p / total for p in prices]
        raw_entropy = -sum(p * math.log(p) for p in probs if p > 0)
        max_entropy = math.log(n)
        entropy = raw_entropy / max_entropy if max_entropy > 0 else 0
    else:
        entropy = 0.0

    # Leader margin (smaller = more competitive = more interesting)
    sorted_prices = sorted(prices, reverse=True)
    if len(sorted_prices) >= 2:
        margin = sorted_prices[0] - sorted_prices[1]
        margin_score = max(0, 1.0 - margin * 2)
    else:
        p = sorted_prices[0]
        margin_score = 1.0 - abs(p - 0.5) * 2

    raw = entropy * 0.6 + margin_score * 0.4
    return round(min(raw * 20, 20), 2)


def _info_independent(prices: list[float]) -> float:
    """Non-negRisk: tradeable ratio + best probability space."""
    n = len(prices)
    if n == 0:
        return 0.0

    # Tradeable market ratio: how many sub-markets have YES in [0.10, 0.90]
    tradeable = sum(1 for p in prices if 0.10 <= p <= 0.90)
    ratio = tradeable / n

    # Best probability space: closest to 0.50
    best_space = max(1.0 - 2.0 * abs(p - 0.5) for p in prices)

    raw = ratio * 0.4 + best_space * 0.6
    return round(min(raw * 20, 20), 2)


# ---------------------------------------------------------------------------
# Dimension 2: Liquidity Aggregate (0-20)
# ---------------------------------------------------------------------------

def _score_liquidity_aggregate(event: EventRow, markets: list[Market]) -> float:
    """Total volume + min depth + coverage ratio."""
    # Event volume (log scale: $5K→0, $50K→0.33, $500K→0.67, $5M→1.0)
    vol = event.volume or 0
    if vol > 0:
        vol_score = min(math.log10(vol / 5000) / 3.0, 1.0)  # log10(1000) = 3
        vol_score = max(vol_score, 0)
    else:
        vol_score = 0.0

    # Min bid depth across active markets (weakest link)
    # If depth data not yet available (pre-orderbook), treat as neutral (0.5)
    depths = [m.total_bid_depth_usd for m in markets if m.total_bid_depth_usd is not None]
    has_depth_data = len(depths) > 0
    if has_depth_data:
        min_depth = min(depths) if depths else 0
        if min_depth > 0:
            depth_score = min(math.log10(max(min_depth, 1)) / 5.0, 1.0)
            depth_score = max(depth_score, 0)
        else:
            depth_score = 0.0
    else:
        depth_score = 0.5  # neutral when no depth data yet

    # Coverage ratio: how many markets have meaningful depth ($100+)
    if has_depth_data and markets:
        with_depth = sum(1 for d in depths if d >= 100)
        coverage = with_depth / len(markets)
    elif not has_depth_data:
        coverage = 0.5  # neutral when no depth data yet
    else:
        coverage = 0.0

    # Combine: volume 40% + min_depth 35% + coverage 25%
    raw = vol_score * 0.40 + depth_score * 0.35 + coverage * 0.25
    return round(min(raw * 20, 20), 2)


# ---------------------------------------------------------------------------
# Dimension 3: Resolution Quality (0-15)
# ---------------------------------------------------------------------------

def _score_resolution_quality(event: EventRow) -> float:
    """Resolution source + description quality."""
    score = 0.0

    # Resolution source present and is URL
    src = event.resolution_source or ""
    if src.startswith("http"):
        score += 0.4
    elif src:
        score += 0.2

    # Description length (proxy for rule clarity)
    desc = event.description or ""
    if len(desc) > 200:
        score += 0.35
    elif len(desc) > 50:
        score += 0.20
    elif len(desc) > 0:
        score += 0.10

    # Objectivity keywords in description
    obj_keywords = ["resolve", "official", "data", "report", "result", "score", "winner", "price"]
    desc_lower = desc.lower()
    obj_matches = sum(1 for kw in obj_keywords if kw in desc_lower)
    score += min(obj_matches * 0.05, 0.25)

    return round(min(score * 15, 15), 2)


# ---------------------------------------------------------------------------
# Dimension 4: Consistency (0-10)
# ---------------------------------------------------------------------------

def _score_consistency(markets: list[Market], *, neg_risk: bool = False) -> float:
    """Overround normality + pricing efficiency.

    Overround (price_sum vs 1.0) only makes sense for negRisk events
    where outcomes are mutually exclusive. For non-negRisk, return neutral.
    """
    prices = [m.yes_price for m in markets if m.yes_price and m.yes_price > 0]
    if not prices:
        return 0.0

    # Non-negRisk: outcomes are independent, overround is meaningless
    if not neg_risk:
        return round(0.7 * 10, 2)

    price_sum = sum(prices)

    # Overround: ideal is 1.0, penalty for deviation
    # |sum - 1.0| → 0 is perfect, >0.3 is bad
    overround = abs(price_sum - 1.0)
    if overround <= 0.05:
        overround_score = 1.0
    elif overround <= 0.15:
        overround_score = 0.7
    elif overround <= 0.30:
        overround_score = 0.4
    else:
        overround_score = 0.1

    # For binary markets (1 sub-market), overround doesn't apply
    if len(prices) == 1:
        overround_score = 0.7  # neutral

    return round(min(overround_score * 10, 10), 2)


# ---------------------------------------------------------------------------
# Dimension 5: Time Window (0-20)
# User insight: 3-7 days is prime trading window. > 60 days filtered at gate.
# ---------------------------------------------------------------------------

def _score_time_window(markets: list[Market]) -> float:
    """Resolution time scoring — steep curve, 1-7 days is sweet spot."""
    now = datetime.now(UTC)
    min_days = None
    for m in markets:
        if m.resolution_time:
            days = (m.resolution_time - now).total_seconds() / 86400
            if days > 0 and (min_days is None or days < min_days):
                min_days = days

    if min_days is None:
        return 0.0  # no data = no score (penalize)

    if min_days < 0.5:
        score = 0.3   # too close, might miss entry
    elif min_days <= 1:
        score = 0.7
    elif min_days <= 7:
        score = 1.0   # prime trading window
    elif min_days <= 14:
        score = 0.8
    elif min_days <= 30:
        score = 0.5
    elif min_days <= 60:
        score = 0.2
    else:
        score = 0.0   # > 60 days (shouldn't reach here, filtered at gate)

    return round(score * 20, 2)


# ---------------------------------------------------------------------------
# Dimension 6: Best Market Quality (0-15)
# Uses the best sub-market's structure score to ensure at least one
# sub-market is actually tradeable. An event with great fundamentals
# but no tradeable sub-market should score low.
# ---------------------------------------------------------------------------

def _score_best_market_quality(markets: list[Market]) -> float:
    """Best sub-market structure score, normalized to 0-15."""
    from scanner.scan.scoring import compute_structure_score

    best = 0.0
    for m in markets:
        score = compute_structure_score(m)
        if score.total > best:
            best = score.total

    # Normalize: 0 → 0, 50 → 7.5, 100 → 15
    return round(min(best / 100 * 15, 15), 2)
