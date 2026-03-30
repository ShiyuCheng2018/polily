"""Hard filters: reject markets that fail strict exclusion rules."""

from dataclasses import dataclass, field

from scanner.config import FiltersConfig, HeuristicsConfig
from scanner.models import Market
from scanner.utils import matches_any


@dataclass
class Rejection:
    market_id: str
    reason: str


@dataclass
class FilterResult:
    passed: list[Market] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)


def apply_hard_filters(
    markets: list[Market],
    filters: FiltersConfig,
    heuristics: HeuristicsConfig,
) -> FilterResult:
    """Apply all hard filters and return passed/rejected split."""
    result = FilterResult()
    for market in markets:
        reason = _check_market(market, filters, heuristics)
        if reason is None:
            result.passed.append(market)
        else:
            result.rejected.append(Rejection(market_id=market.market_id, reason=reason))
    return result


def _check_market(
    m: Market,
    f: FiltersConfig,
    h: HeuristicsConfig,
) -> str | None:
    """Return rejection reason, or None if market passes all filters."""

    # Binary market check
    if f.require_binary_market and not m.is_binary:
        return "Not a binary market"

    # Resolution time required
    if m.resolution_time is None:
        return "No resolution time"

    # Price required
    if m.yes_price is None:
        return "No yes_price available"

    # Probability check
    if m.yes_price < f.hard_reject_below_yes_price:
        return f"Probability too low ({m.yes_price:.2f} < {f.hard_reject_below_yes_price})"
    if m.yes_price > f.hard_reject_above_yes_price:
        return f"Probability too high ({m.yes_price:.2f} > {f.hard_reject_above_yes_price})"

    # Time to resolution
    days = m.days_to_resolution
    if days is not None:
        if days < f.min_days_to_resolution:
            return f"Too close to resolution ({days:.1f}d < {f.min_days_to_resolution}d)"
        if days > f.max_days_to_resolution:
            return f"Too far from resolution ({days:.1f}d > {f.max_days_to_resolution}d)"

    # Spread check
    spread_pct = m.spread_pct_yes
    if spread_pct is not None and spread_pct > f.max_spread_pct_yes:
        return f"Spread too wide ({spread_pct:.1%} > {f.max_spread_pct_yes:.1%})"

    # Round-trip friction
    friction = m.round_trip_friction_pct
    if friction is not None and friction > f.max_round_trip_friction_pct:
        return f"Round-trip friction too high ({friction:.1%} > {f.max_round_trip_friction_pct:.1%})"

    # Volume
    if m.volume is not None and m.volume < f.min_volume:
        return f"Volume too low ({m.volume:.0f} < {f.min_volume})"

    # Open interest
    if m.open_interest is not None and m.open_interest < f.min_open_interest:
        return f"Open interest too low ({m.open_interest:.0f} < {f.min_open_interest})"

    # Order book depth
    bid_depth = m.total_bid_depth_usd
    if bid_depth is not None and bid_depth < f.min_bid_depth_usd:
        return f"Bid depth too shallow (${bid_depth:.0f} < ${f.min_bid_depth_usd})"

    # Objectivity check
    title_lower = m.title.lower()
    if f.require_objective_market:
        for kw in h.objective_blacklist_keywords:
            if kw.lower() in title_lower:
                return f"Subjective market keyword detected: '{kw}'"

    # Noise market: keyword check
    if matches_any(m.title, h.noise_market_keywords):
        return "Noise market keyword detected"

    # Noise market: short duration + noise category
    if days is not None and days < h.noise_max_days and m.category in h.noise_categories:
        return f"Ultra-short noise market ({days:.2f}d in {m.category})"

    # Long-dated narrative
    if f.reject_long_dated_narrative_markets and days is not None:
        if days > f.long_dated_narrative_days_cutoff:
            if matches_any(m.title, h.narrative_market_keywords):
                return "Long-dated narrative market"

    return None
