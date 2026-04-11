"""Event-level quality scoring — 5 dimensions.

Determines if an event is worth researching. Uses event-level aggregates,
not individual sub-market quality.

Dimensions:
  1. Information Value (25)  — entropy, leader margin, HHI
  2. Liquidity Aggregate (25) — volume, min depth, coverage ratio
  3. Resolution Quality (20) — resolution source, description quality
  4. Consistency (15) — overround, pricing efficiency
  5. Time Window (15) — resolution in sweet spot
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
    """Event-level quality score with 5 dimensions."""

    information_value: float = 0.0    # 0-25
    liquidity_aggregate: float = 0.0  # 0-25
    resolution_quality: float = 0.0   # 0-20
    consistency: float = 0.0          # 0-15
    time_window: float = 0.0          # 0-15
    total: float = 0.0                # 0-100


def compute_event_quality_score(
    event: EventRow,
    markets: list[Market],
) -> EventQualityScore:
    """Compute event-level quality score from event + sub-market data."""
    active = [m for m in markets if m.yes_price and m.yes_price > 0]
    if not active:
        return EventQualityScore()

    info = _score_information_value(active)
    liq = _score_liquidity_aggregate(event, active)
    res = _score_resolution_quality(event)
    con = _score_consistency(active)
    time = _score_time_window(active)

    return EventQualityScore(
        information_value=info,
        liquidity_aggregate=liq,
        resolution_quality=res,
        consistency=con,
        time_window=time,
        total=round(info + liq + res + con + time, 2),
    )


# ---------------------------------------------------------------------------
# Dimension 1: Information Value (0-25)
# ---------------------------------------------------------------------------

def _score_information_value(markets: list[Market]) -> float:
    """Entropy + leader margin → how uncertain/interesting is this event."""
    prices = [m.yes_price for m in markets if m.yes_price and m.yes_price > 0]
    if not prices:
        return 0.0

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
        # 0 margin → 1.0, 0.5 margin → 0.0
        margin_score = max(0, 1.0 - margin * 2)
    else:
        # Binary market: distance from 0.5
        p = sorted_prices[0]
        margin_score = 1.0 - abs(p - 0.5) * 2  # 0.5 → 1.0, 0/1 → 0.0

    # Combine: entropy 60% + margin 40%
    raw = entropy * 0.6 + margin_score * 0.4
    return round(min(raw * 25, 25), 2)


# ---------------------------------------------------------------------------
# Dimension 2: Liquidity Aggregate (0-25)
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
    return round(min(raw * 25, 25), 2)


# ---------------------------------------------------------------------------
# Dimension 3: Resolution Quality (0-20)
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

    return round(min(score * 20, 20), 2)


# ---------------------------------------------------------------------------
# Dimension 4: Consistency (0-15)
# ---------------------------------------------------------------------------

def _score_consistency(markets: list[Market]) -> float:
    """Overround normality + pricing efficiency."""
    prices = [m.yes_price for m in markets if m.yes_price and m.yes_price > 0]
    if not prices:
        return 0.0

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

    return round(min(overround_score * 15, 15), 2)


# ---------------------------------------------------------------------------
# Dimension 5: Time Window (0-15)
# ---------------------------------------------------------------------------

def _score_time_window(markets: list[Market]) -> float:
    """Resolution in sweet spot (1-30 days)."""
    # Get minimum days to resolution across active markets
    now = datetime.now(UTC)
    min_days = None
    for m in markets:
        if m.resolution_time:
            days = (m.resolution_time - now).total_seconds() / 86400
            if days > 0 and (min_days is None or days < min_days):
                min_days = days

    if min_days is None:
        return 7.5  # neutral when unknown

    # Sweet spot: 1-14 days → full score
    # < 0.5 days → too close (might miss)
    # > 60 days → too far (capital lock)
    if min_days < 0.5:
        score = 0.3
    elif min_days <= 1:
        score = 0.6
    elif min_days <= 14:
        score = 1.0
    elif min_days <= 30:
        score = 0.8
    elif min_days <= 60:
        score = 0.5
    else:
        score = 0.2

    return round(score * 15, 2)
