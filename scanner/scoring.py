"""Beauty Score: weighted 0-100 score measuring market structure quality."""

from dataclasses import dataclass

from scanner.config import FiltersConfig, ScoringWeights
from scanner.models import Market


@dataclass
class ScoreBreakdown:
    time_to_resolution: float
    objectivity: float
    probability_zone: float
    liquidity_depth: float
    exitability: float
    catalyst_proxy: float
    small_account_friendliness: float
    total: float


def normalize_weights(
    base: ScoringWeights,
    overrides: dict[str, int] | None = None,
) -> dict[str, float]:
    """Apply overrides then renormalize so weights sum to 100."""
    raw = {
        "time_to_resolution": base.time_to_resolution,
        "objectivity": base.objectivity,
        "probability_zone": base.probability_zone,
        "liquidity_depth": base.liquidity_depth,
        "exitability": base.exitability,
        "catalyst_proxy": base.catalyst_proxy,
        "small_account_friendliness": base.small_account_friendliness,
    }
    if overrides:
        for k, v in overrides.items():
            if k in raw:
                raw[k] = v

    total = sum(raw.values())
    if total == 0:
        return {k: 0.0 for k in raw}
    factor = 100.0 / total
    return {k: v * factor for k, v in raw.items()}


def compute_beauty_score(
    market: Market,
    weights: ScoringWeights,
    filters: FiltersConfig,
    weight_overrides: dict[str, int] | None = None,
    objectivity_score: int | None = None,
    probability_penalty_mode: str = "mid_bias",
) -> ScoreBreakdown:
    """Compute a 0-100 beauty score with component breakdown.

    Each component is scored 0.0-1.0, then multiplied by its normalized weight.
    objectivity_score: if provided (from AI Agent 1), use it; otherwise use a simple heuristic.
    """
    w = normalize_weights(weights, weight_overrides)

    time_score = _score_time(market, filters)
    obj_score = _score_objectivity(market, objectivity_score)
    prob_score = _score_probability(market, filters, probability_penalty_mode)
    liq_score = _score_liquidity(market, filters)
    exit_score = _score_exitability(market)
    cat_score = _score_catalyst(market)
    small_score = _score_small_account(market, filters)

    breakdown = ScoreBreakdown(
        time_to_resolution=round(time_score * w["time_to_resolution"], 2),
        objectivity=round(obj_score * w["objectivity"], 2),
        probability_zone=round(prob_score * w["probability_zone"], 2),
        liquidity_depth=round(liq_score * w["liquidity_depth"], 2),
        exitability=round(exit_score * w["exitability"], 2),
        catalyst_proxy=round(cat_score * w["catalyst_proxy"], 2),
        small_account_friendliness=round(small_score * w["small_account_friendliness"], 2),
        total=0,
    )
    breakdown.total = round(
        breakdown.time_to_resolution + breakdown.objectivity + breakdown.probability_zone
        + breakdown.liquidity_depth + breakdown.exitability + breakdown.catalyst_proxy
        + breakdown.small_account_friendliness,
        2,
    )
    return breakdown


def _score_time(m: Market, f: FiltersConfig) -> float:
    """0-1: prefer 0.5-7 days, accept up to 14."""
    days = m.days_to_resolution
    if days is None:
        return 0.0
    if f.preferred_min_days_to_resolution <= days <= f.preferred_max_days_to_resolution:
        return 1.0
    if days < f.preferred_min_days_to_resolution:
        return max(0.0, days / f.preferred_min_days_to_resolution)
    # Between preferred max and hard max
    if days <= f.max_days_to_resolution:
        span = f.max_days_to_resolution - f.preferred_max_days_to_resolution
        if span == 0:
            return 0.5
        return max(0.0, 1.0 - (days - f.preferred_max_days_to_resolution) / span * 0.5)
    return 0.0


def _score_objectivity(m: Market, ai_score: int | None = None) -> float:
    """0-1: if AI agent provided a score (0-100), use it. Otherwise simple heuristic."""
    if ai_score is not None:
        return min(1.0, ai_score / 100.0)
    # Simple heuristic: binary market + has rules text
    score = 0.5  # baseline
    if m.is_binary:
        score += 0.2
    if m.rules and len(m.rules) > 50:
        score += 0.15
    if m.resolution_source:
        score += 0.15
    return min(1.0, score)


def _score_probability(m: Market, f: FiltersConfig, mode: str = "mid_bias") -> float:
    """0-1: score based on probability zone.

    Modes:
    - "mid_bias": prefer 0.30-0.70, penalize extremes (default)
    - "flat": uniform score in 0.20-0.80, only penalize hard edges
    - "disabled": always return 1.0
    """
    p = m.yes_price
    if p is None:
        return 0.0
    if mode == "disabled":
        return 1.0
    if mode == "flat":
        # No penalty within acceptable range — full score
        if f.min_yes_price <= p <= f.max_yes_price:
            return 1.0
        return 0.0
    # Default: mid_bias
    if f.preferred_min_yes_price <= p <= f.preferred_max_yes_price:
        # Peak at 0.50, taper toward preferred edges
        distance_from_center = abs(p - 0.50)
        return 1.0 - distance_from_center  # 0.50 → 1.0, 0.30/0.70 → 0.8
    if f.min_yes_price <= p <= f.max_yes_price:
        # Acceptable range: linearly interpolate from 0 at hard boundary
        # to match the preferred boundary score for continuity
        if p < f.preferred_min_yes_price:
            preferred_edge_score = 1.0 - abs(f.preferred_min_yes_price - 0.50)
            span = f.preferred_min_yes_price - f.min_yes_price
            if span == 0:
                return preferred_edge_score
            ratio = (p - f.min_yes_price) / span
            return ratio * preferred_edge_score
        else:
            preferred_edge_score = 1.0 - abs(f.preferred_max_yes_price - 0.50)
            span = f.max_yes_price - f.preferred_max_yes_price
            if span == 0:
                return preferred_edge_score
            ratio = (f.max_yes_price - p) / span
            return ratio * preferred_edge_score
    return 0.0


def _score_liquidity(m: Market, f: FiltersConfig) -> float:
    """0-1: based on spread and order book depth."""
    score = 0.0

    # Spread component (60% of liquidity score)
    spread = m.spread_pct_yes
    if spread is not None:
        if spread <= f.preferred_max_spread_pct_yes:
            score += 0.6
        elif spread <= f.max_spread_pct_yes:
            denom = f.max_spread_pct_yes - f.preferred_max_spread_pct_yes
            ratio = (f.max_spread_pct_yes - spread) / denom if denom > 0 else 0.5
            score += 0.3 + 0.3 * ratio
        else:
            score += 0.1

    # Depth component (40% of liquidity score)
    bid_depth = m.total_bid_depth_usd
    if bid_depth is not None:
        depth_ceiling = 2000.0
        if bid_depth >= depth_ceiling:
            score += 0.4
        elif bid_depth >= f.min_bid_depth_usd:
            denom = depth_ceiling - f.min_bid_depth_usd
            ratio = (bid_depth - f.min_bid_depth_usd) / denom if denom > 0 else 0.5
            score += 0.2 + 0.2 * ratio
        else:
            score += 0.05

    return min(1.0, score)


def _score_exitability(m: Market) -> float:
    """0-1: based on bid-side depth and time to resolution."""
    score = 0.5  # baseline

    # Bid depth indicates ability to sell
    bid_depth = m.total_bid_depth_usd
    if bid_depth is not None:
        if bid_depth >= 1000:
            score += 0.3
        elif bid_depth >= 200:
            score += 0.15

    # More time = easier to exit
    days = m.days_to_resolution
    if days is not None and days >= 1.0:
        score += 0.2
    elif days is not None and days >= 0.5:
        score += 0.1

    return min(1.0, score)


def _score_catalyst(m: Market) -> float:
    """0-1: heuristic catalyst proxy from title and time."""
    score = 0.3  # baseline

    title_lower = m.title.lower()
    catalyst_keywords = ["by", "before", "on", "deadline", "vote", "release", "announcement", "report"]
    hits = sum(1 for kw in catalyst_keywords if kw in title_lower)
    score += min(0.4, hits * 0.1)

    # Near resolution suggests catalyst
    days = m.days_to_resolution
    if days is not None and 0.5 <= days <= 3:
        score += 0.3
    elif days is not None and 3 < days <= 7:
        score += 0.15

    return min(1.0, score)


def _score_small_account(m: Market, f: FiltersConfig) -> float:
    """0-1: friendliness for a small ($10-20) trade."""
    score = 0.5  # baseline

    # Low friction is key
    friction = m.round_trip_friction_pct
    if friction is not None:
        if friction < 0.04:
            score += 0.3
        elif friction < 0.06:
            score += 0.15

    # Sufficient depth for $20
    bid_depth = m.total_bid_depth_usd
    if bid_depth is not None and bid_depth >= 500:
        score += 0.2

    return min(1.0, score)
