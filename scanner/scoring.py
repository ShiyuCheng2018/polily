"""Structure Score: weighted 0-100 score measuring market tradability.

5-dimension system:
  1. Liquidity Structure (30) — spread + log-scale depth + bid/ask balance
  2. Objective Verifiability (25) — resolution quality, baseline=0
  3. Probability Space (20) — symmetric min(p, 1-p) linear
  4. Time Structure (15) — sweet spot [1,5] days + catalyst proximity
  5. Trading Friction (10) — pure friction 6-tier
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scanner.config import ScoringWeights
from scanner.models import Market

if TYPE_CHECKING:
    from scanner.mispricing import MispricingResult


@dataclass
class ScoreBreakdown:
    liquidity_structure: float      # 0-30
    objective_verifiability: float  # 0-25
    probability_space: float        # 0-20
    time_structure: float           # 0-15
    trading_friction: float         # 0-10
    total: float                    # 0-100


def compute_structure_score(
    market: Market,
    weights: ScoringWeights,
) -> ScoreBreakdown:
    """Compute a 0-100 structure score with 5-dimension breakdown.

    Each component is scored 0.0-1.0, then multiplied by its weight.
    """
    liq = _score_liquidity_structure(market)
    obj = _score_objective_verifiability(market)
    prob = _score_probability_space(market)
    time = _score_time_structure(market)
    fric = _score_trading_friction(market)

    breakdown = ScoreBreakdown(
        liquidity_structure=round(liq * weights.liquidity_structure, 2),
        objective_verifiability=round(obj * weights.objective_verifiability, 2),
        probability_space=round(prob * weights.probability_space, 2),
        time_structure=round(time * weights.time_structure, 2),
        trading_friction=round(fric * weights.trading_friction, 2),
        total=0,
    )
    breakdown.total = round(
        breakdown.liquidity_structure
        + breakdown.objective_verifiability
        + breakdown.probability_space
        + breakdown.time_structure
        + breakdown.trading_friction,
        2,
    )
    return breakdown


# ---------------------------------------------------------------------------
# Dimension 1: Liquidity Structure (weight 30)
# spread(40%) + log-scale depth(35%) + bid/ask balance(25%)
# ---------------------------------------------------------------------------

def _score_liquidity_structure(m: Market) -> float:
    score = 0.0

    # Spread component (40%)
    spread = m.spread_pct_yes
    if spread is not None:
        if spread <= 0.01:
            score += 0.40
        elif spread <= 0.02:
            score += 0.35
        elif spread <= 0.03:
            score += 0.28
        elif spread <= 0.05:
            score += 0.18
        elif spread <= 0.08:
            score += 0.08
        # else 0

    # Log-scale depth component (35%)
    # Use log10 scale: $100→0.2, $1K→0.5, $10K→0.8, $100K→1.0
    bid_depth = m.total_bid_depth_usd
    if bid_depth is not None and bid_depth > 0:
        # log10(100)=2, log10(100000)=5; map [2,5] → [0,1]
        log_depth = math.log10(max(bid_depth, 1))
        depth_ratio = min(1.0, max(0.0, (log_depth - 2) / 3))
        score += 0.35 * depth_ratio

    # Bid/ask balance component (25%)
    # Perfect balance = 1.0, heavy imbalance = 0.0
    bid = m.total_bid_depth_usd
    ask = m.total_ask_depth_usd
    if bid is not None and ask is not None and (bid + ask) > 0:
        smaller = min(bid, ask)
        larger = max(bid, ask)
        balance = smaller / larger if larger > 0 else 0
        score += 0.25 * balance

    return min(1.0, score)


# ---------------------------------------------------------------------------
# Dimension 2: Objective Verifiability (weight 25)
# baseline=0, additive: resolution_source, rules, title analysis, penalties
# ---------------------------------------------------------------------------

_SUBJECTIVE_PATTERNS = re.compile(
    r"\b(best|most|greatest|worst|better|worse|top|"
    r"favorite|popular|likely to|will .+ be remembered|"
    r"coolest|funniest|biggest impact)\b",
    re.IGNORECASE,
)

_OBJECTIVE_SIGNALS = re.compile(
    r"\b(price|above|below|reach|exceed|by .+ date|"
    r"before|on .+ \d{4}|vote|pass|win|elect|"
    r"announce|release|report|data|deadline|"
    r"GDP|CPI|rate|percent)\b",
    re.IGNORECASE,
)


def _score_objective_verifiability(m: Market) -> float:
    score = 0.0

    # Resolution source: strong signal (+0.30)
    if m.resolution_source and len(m.resolution_source.strip()) > 3:
        score += 0.30

    # Rules text quality
    if m.rules:
        rules_len = len(m.rules)
        if rules_len > 200:
            score += 0.25
        elif rules_len > 100:
            score += 0.15
        elif rules_len > 30:
            score += 0.08

    # Title content analysis — objective keywords
    title = m.title
    if _OBJECTIVE_SIGNALS.search(title):
        score += 0.20

    # Description bonus
    if m.description and len(m.description) > 50:
        score += 0.10

    # Binary market bonus
    if m.is_binary:
        score += 0.10

    # Subjective penalty
    if _SUBJECTIVE_PATTERNS.search(title):
        score -= 0.25
    if m.description and _SUBJECTIVE_PATTERNS.search(m.description):
        score -= 0.10

    return min(1.0, max(0.0, score))


# ---------------------------------------------------------------------------
# Dimension 3: Probability Space (weight 20)
# Symmetric: min(p, 1-p), linear from 0.50→1.0 to 0.10→0.0
# ---------------------------------------------------------------------------

def _score_probability_space(m: Market) -> float:
    p = m.yes_price
    if p is None:
        return 0.0
    # min(p, 1-p) maps [0,0.5] → [0,0.5]
    # Normalize: 0.50→1.0, 0.30→0.50, 0.10→0.0, <0.10→0.0
    room = min(p, 1 - p)
    if room >= 0.50:
        return 1.0
    if room <= 0.10:
        return 0.0
    # Linear: 0.10→0.0, 0.50→1.0
    return (room - 0.10) / 0.40


# ---------------------------------------------------------------------------
# Dimension 4: Time Structure (weight 15)
# Sweet spot [1,5] days (70%) + catalyst proximity (30%)
# ---------------------------------------------------------------------------

def _score_time_structure(m: Market) -> float:
    days = m.days_to_resolution
    if days is None:
        return 0.0

    # Time window component (70%)
    if 1.0 <= days <= 5.0:
        time_score = 1.0
    elif 0.5 <= days < 1.0:
        time_score = 0.6
    elif 5.0 < days <= 7.0:
        time_score = 0.7
    elif 7.0 < days <= 14.0:
        # Linear decay from 0.5 at 7d to 0.1 at 14d
        time_score = 0.5 - 0.4 * (days - 7) / 7
    elif days < 0.5:
        time_score = 0.3  # too soon, hard to act
    else:
        time_score = 0.0  # > 14 days

    # Catalyst proximity component (30%)
    # Near resolution = stronger catalyst signal
    catalyst = 0.0
    if 0.5 <= days <= 2.0:
        catalyst = 1.0
    elif 2.0 < days <= 5.0:
        catalyst = 0.7
    elif 5.0 < days <= 7.0:
        catalyst = 0.4
    elif 7.0 < days <= 14.0:
        catalyst = 0.2

    return min(1.0, time_score * 0.70 + catalyst * 0.30)


# ---------------------------------------------------------------------------
# Dimension 5: Trading Friction (weight 10)
# Pure friction 6-tier
# ---------------------------------------------------------------------------

def _score_trading_friction(m: Market) -> float:
    friction = m.round_trip_friction_pct
    if friction is None:
        return 0.0  # no data = assume bad
    if friction < 0.02:
        return 1.0
    if friction < 0.03:
        return 0.85
    if friction < 0.04:
        return 0.65
    if friction < 0.06:
        return 0.40
    if friction < 0.08:
        return 0.15
    return 0.0


# ---------------------------------------------------------------------------
# Three-score system: quality / value / edge
# ---------------------------------------------------------------------------

def compute_three_scores(
    breakdown: ScoreBreakdown,
    mispricing: MispricingResult,
    market: Market,
) -> dict[str, float | None]:
    """Compute three independent dimension scores.

    - quality (0-100): is this market tradable? (from structure score)
    - value (0-100): is the current price worth trading? (edge vs friction)
    - edge (0-100 or None): directional advantage (only with mispricing direction)
    """
    # Quality: direct from structure score (already 0-100)
    quality = min(100, breakdown.total)

    # Value = max(quantitative_value, structural_value)
    edge_pct = mispricing.deviation_pct if mispricing.deviation_pct is not None else 0
    friction = market.round_trip_friction_pct if market.round_trip_friction_pct is not None else 0.04
    if edge_pct > 0:
        net_edge = max(0, edge_pct - friction)
        quant_value = min(100, net_edge / 0.10 * 100)
    else:
        quant_value = 0.0

    # Structural value for ALL markets — continuous scales
    struct_value = 0.0

    # 1. Probability room (max 20) — symmetric linear from min(p, 1-p)
    p = market.yes_price
    if p is not None:
        room = min(p, 1 - p)  # 0.50→0.50, 0.30→0.30, 0.20→0.20
        struct_value += max(0, min(20, (room - 0.10) / 0.40 * 20))

    # 2. Friction advantage (max 30) — continuous inverse, steeper penalty
    #    0%→30, 2%→22, 4%→15, 6%→7, 8%→0
    struct_value += max(0, min(30, (1 - friction / 0.08) * 30))

    # 3. Depth (max 20) — log scale, calibrated for Polymarket reality
    #    $100→0, $1K→5, $10K→10, $100K→15, $1M→20
    bid = market.total_bid_depth_usd
    if bid is not None and bid > 0:
        log_d = math.log10(max(bid, 100))
        struct_value += max(0, min(20, (log_d - 2) / 4 * 20))

    # 4. Time window (max 15) — peak at [1,5] days, decay outside
    days = market.days_to_resolution
    if days is not None:
        if 1.0 <= days <= 5.0:
            struct_value += 15
        elif 0.5 <= days < 1.0:
            struct_value += 8
        elif 5.0 < days <= 7.0:
            struct_value += 10
        elif 7.0 < days <= 14.0:
            struct_value += max(0, 10 - (days - 7) / 7 * 10)

    # 5. Spread tightness (max 15) — continuous
    #    0%→15, 1%→12, 2%→9, 3%→6, 5%→0
    spread = market.spread_pct_yes
    if spread is not None:
        struct_value += max(0, min(15, (1 - spread / 0.05) * 15))

    value = max(quant_value, struct_value)

    # Direction edge: only with mispricing direction + model confidence
    direction = mispricing.direction
    confidence = mispricing.model_confidence
    edge_score: float | None = None
    if direction and confidence and edge_pct > 0:
        confidence_mult = {"high": 1.0, "medium": 0.7, "low": 0.4}.get(confidence, 0.4)
        edge_score = min(100, edge_pct / 0.10 * 100 * confidence_mult)

    return {
        "quality": round(quality, 1),
        "value": round(value, 1),
        "edge": round(edge_score, 1) if edge_score is not None else None,
    }
