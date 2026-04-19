"""Structure Score: weighted 0-100 score measuring market tradability.

5-dimension system (weights are type-specific, see _TYPE_WEIGHTS / _DEFAULT_WEIGHTS):
  1. Liquidity Structure — spread + log-scale depth + bid/ask balance
  2. Objective Verifiability — resolution quality, baseline=0
  3. Probability Space — symmetric min(p, 1-p) linear
  4. Time Structure — sweet spot [1,5] days + catalyst proximity
  5. Trading Friction — pure friction 6-tier
  +  Net Edge (crypto only) — |deviation%| - round_trip_friction
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from scanner.core.models import Market

if TYPE_CHECKING:
    from scanner.scan.mispricing import MispricingResult


@dataclass
class ScoreBreakdown:
    liquidity_structure: float      # 0-W (type-dependent max)
    objective_verifiability: float  # 0-W
    probability_space: float        # 0-W
    time_structure: float           # 0-W
    trading_friction: float         # 0-W
    net_edge: float = 0.0           # 0-W (crypto only, 0 for others)
    total: float = 0.0             # 0-100


# Type-specific weight profiles (all sum to 100)
_TYPE_WEIGHTS = {
    "crypto": {
        "liquidity": 22, "verifiability": 10, "probability": 15,
        "time": 18, "friction": 10, "net_edge": 25,
    },
    "sports": {
        "liquidity": 30, "verifiability": 10, "probability": 20,
        "time": 25, "friction": 15, "net_edge": 0,
    },
    "political": {
        "liquidity": 30, "verifiability": 10, "probability": 20,
        "time": 25, "friction": 15, "net_edge": 0,
    },
}
_DEFAULT_WEIGHTS = {
    "liquidity": 30, "verifiability": 10, "probability": 20,
    "time": 25, "friction": 15, "net_edge": 0,
}


def compute_structure_score(
    market: Market,
    mispricing: object | None = None,
) -> ScoreBreakdown:
    """Compute a 0-100 structure score with type-specific weight profiles.

    Crypto markets get Net Edge dimension (25%), others get 0%.
    Pass mispricing (MispricingResult) to enable net_edge scoring for crypto.
    """
    market_type = getattr(market, "market_type", None) or "other"
    tw = _TYPE_WEIGHTS.get(market_type, _DEFAULT_WEIGHTS)

    liq = _score_liquidity_structure(market)
    obj = _score_objective_verifiability(market)
    prob = _score_probability_space(market)
    time = _score_time_structure(market)
    fric = _score_trading_friction(market)

    # Net edge: only for crypto with mispricing data
    ne = 0.0
    if tw["net_edge"] > 0 and mispricing is not None:
        ne = _score_net_edge(market, mispricing)

    breakdown = ScoreBreakdown(
        liquidity_structure=round(liq * tw["liquidity"], 2),
        objective_verifiability=round(obj * tw["verifiability"], 2),
        probability_space=round(prob * tw["probability"], 2),
        time_structure=round(time * tw["time"], 2),
        trading_friction=round(fric * tw["friction"], 2),
        net_edge=round(ne * tw["net_edge"], 2),
    )
    breakdown.total = round(
        breakdown.liquidity_structure
        + breakdown.objective_verifiability
        + breakdown.probability_space
        + breakdown.time_structure
        + breakdown.trading_friction
        + breakdown.net_edge,
        2,
    )
    return breakdown


def _score_net_edge(market: Market, mispricing: object) -> float:
    """Score net edge for crypto markets (0-1).

    Net Edge = |deviation_pct| - round_trip_friction.
    Higher net edge (after friction) = better score.
    """
    deviation = getattr(mispricing, "deviation_pct", None)
    if not deviation:
        return 0.0

    # No bid = can't exit position, edge is theoretical only
    if not market.total_bid_depth_usd:
        return 0.0

    deviation = abs(deviation)  # overpriced (NO side) edge also counts

    friction = market.round_trip_friction_pct or 0.04
    net = deviation - friction

    if net <= 0:
        return 0.0

    # Map net edge to 0-1: 0%→0, 5%→0.5, 10%+→1.0
    return min(1.0, net / 0.10)


# ---------------------------------------------------------------------------
# Dimension 1: Liquidity Structure (weight 30)
# spread(40%) + log-scale depth(35%) + bid/ask balance(25%)
# ---------------------------------------------------------------------------

def _score_liquidity_structure(m: Market) -> float:
    score = 0.0

    # Spread component (40%) — best-side % so low-YES markets aren't penalized
    # for a cost the user would never pay (they'd buy NO instead).
    spread = m.spread_pct_best_side
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

# Vague resolution criteria — penalize when in description/rules
_VAGUE_RESOLUTION = re.compile(
    r"\b(qualifying|significant|major|meaningful|substantial|"
    r"credible|notable|material|effectively|largely|"
    r"sole discretion|reasonably|in .+ judgment)\b",
    re.IGNORECASE,
)

_OBJECTIVE_SIGNALS = re.compile(
    r"\b(price|above|below|reach|exceed|by .+ date|"
    r"before|on .+ \d{4}|vote|pass|win|elect|"
    r"announce|release|report|data|deadline|"
    r"GDP|CPI|interest rate|rate cut|rate hike|rate decision|percent)\b",
    re.IGNORECASE,
)


def _score_objective_verifiability(m: Market) -> float:
    """Two-layer verifiability scoring.

    Layer 1 — Resolution type (0.0-0.50):
      Numeric threshold (price > X @ source)  → 0.50
      Official result (election, score)       → 0.40
      Event occurrence (announce, sign, pass)  → 0.25
      Status judgment (conflict ends, recession) → 0.10

    Layer 2 — Source quality (0.0-0.50):
      API-grade data source URL               → 0.50
      News/official org URL                   → 0.30
      Text description with resolve rules     → 0.15
      No description                          → 0.00
    """
    rules_and_desc = (m.rules or "") + " " + (m.description or "")
    title = m.title

    # --- Layer 1: Resolution type classification ---
    layer1 = 0.10  # default: status judgment

    # Numeric threshold: price/above/below + number + data source
    if re.search(r'\b(price|above|below|exceed|reach)\b', title, re.IGNORECASE) and \
       re.search(r'\$[\d,]+|\d{2,}', title):
        layer1 = 0.50
    # Numeric count: tweets, posts, followers, "# of"
    elif re.search(r'#\s*\w+|how many|number of|\b(count|total|tweets|posts|followers)\b', title, re.IGNORECASE):
        layer1 = 0.45
    # Official result: election, score, vote count, central bank decision
    elif re.search(r'\b(win|elect|vote|score|medal|rank|seed|draft|make the|decision|ruling|verdict)\b', title, re.IGNORECASE):
        layer1 = 0.40
    # Official data release: rate, CPI, GDP, Fed, BOJ, ECB
    elif re.search(r'\b(interest rate|rate cut|rate hike|rate decision|CPI|GDP|inflation|Fed|BOJ|ECB|BOE|RBA|FOMC|basis points?|bps)\b', title + " " + rules_and_desc, re.IGNORECASE):
        layer1 = 0.45
    # Event occurrence: announce, release, sign, pass, approve
    elif re.search(r'\b(announce|release|sign|pass|approve|launch|confirm|file)\b', title, re.IGNORECASE):
        layer1 = 0.25

    # Vague resolution penalty on Layer 1
    vague_hits = len(_VAGUE_RESOLUTION.findall(rules_and_desc))
    if vague_hits >= 3:
        layer1 = min(layer1, 0.10)
    elif vague_hits >= 1:
        layer1 *= 0.7

    # Subjective title penalty
    if _SUBJECTIVE_PATTERNS.search(title):
        layer1 *= 0.5

    # --- Layer 2: Source quality ---
    layer2 = 0.0

    # Check for API-grade data sources (Binance, CoinGecko, BLS, etc.)
    _API_SOURCES = re.compile(
        r'binance|coinbase|coingecko|kraken|bls\.gov|fred\.|'
        r'boj\.or\.jp|ecb\.europa|federalreserve\.gov|boe\.co\.uk|rba\.gov|'
        r'espn|nfl\.com|nba\.com|mlb\.com|fifa\.com|'
        r'fec\.gov|sec\.gov|gov\.uk|\.gov\b|'
        r'ap news|associated press|reuters',
        re.IGNORECASE,
    )
    src = m.resolution_source or ""
    if src and re.search(r'https?://', src):
        if _API_SOURCES.search(src):
            layer2 = 0.50  # API-grade
        else:
            layer2 = 0.30  # some URL
    elif _API_SOURCES.search(rules_and_desc):
        layer2 = 0.40  # mentioned in description
    elif re.search(r'https?://', rules_and_desc):
        layer2 = 0.25  # URL in description
    elif re.search(r'resolve.{1,30}(yes|no)', rules_and_desc, re.IGNORECASE):
        layer2 = 0.15  # has resolve rules text
    elif len(rules_and_desc.strip()) > 50:
        layer2 = 0.10  # some description

    return min(1.0, max(0.0, layer1 + layer2))


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
        # Linear decay from 0.5 at 7d to 0.2 at 14d
        time_score = 0.5 - 0.3 * (days - 7) / 7
    elif 14.0 < days <= 30.0:
        # Slow decay from 0.2 at 14d to 0.05 at 30d
        time_score = 0.2 - 0.15 * (days - 14) / 16
    elif days < 0.5:
        time_score = 0.3  # too soon, hard to act
    else:
        time_score = 0.0  # > 30 days

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

    # 5. Spread tightness (max 15) — continuous, on the best tradeable side.
    #    0%→15, 1%→12, 2%→9, 3%→6, 5%→0
    spread = market.spread_pct_best_side
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
