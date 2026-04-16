"""Hard filters: reject events/markets that fail strict exclusion rules."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from scanner.core.config import FiltersConfig, HeuristicsConfig
from scanner.core.event_store import EventRow
from scanner.core.models import Market
from scanner.utils import matches_any

# Default thresholds for event-level filtering
_MIN_EVENT_VOLUME = 5000  # $5K total volume


@dataclass
class Rejection:
    market_id: str
    reason: str


@dataclass
class EventRejection:
    event_id: str
    reason: str


@dataclass
class FilterResult:
    passed: list[Market] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)


@dataclass
class EventFilterResult:
    """Result of event-level filtering."""
    passed_event_ids: set[str] = field(default_factory=set)
    passed_markets: list[Market] = field(default_factory=list)  # ALL sub-markets of passed events
    rejected: list[EventRejection] = field(default_factory=list)


def filter_events(
    event_market_pairs: list[tuple[EventRow, list[Market]]],
    min_volume: float = _MIN_EVENT_VOLUME,
) -> EventFilterResult:
    """Filter at event level. When an event passes, ALL its sub-markets are included.

    Event-level criteria:
    - Has at least one sub-market with a valid price (> 0)
    - Event total volume >= min_volume
    - Event end_date not in the past (if set)
    - Event title is not noise
    """
    result = EventFilterResult()

    for event, markets in event_market_pairs:
        reason = _check_event(event, markets, min_volume)
        if reason is None:
            result.passed_event_ids.add(event.event_id)
            result.passed_markets.extend(markets)
        else:
            result.rejected.append(EventRejection(event_id=event.event_id, reason=reason))

    return result


def _check_event(
    ev: EventRow,
    markets: list[Market],
    min_volume: float,
) -> str | None:
    """Return rejection reason, or None if event passes."""

    # Must have at least one sub-market
    if not markets:
        return "No sub-markets"

    # Must have at least one sub-market with valid price
    has_valid_price = any(m.yes_price and m.yes_price > 0 for m in markets)
    if not has_valid_price:
        return "No sub-market with valid price"

    # Volume check (event-level aggregate)
    if ev.volume is not None and ev.volume < min_volume:
        return f"Event volume too low (${ev.volume:,.0f} < ${min_volume:,.0f})"

    # End date check — reject if ALL sub-markets are past resolution
    if ev.end_date:
        try:
            end = datetime.fromisoformat(ev.end_date.replace("Z", "+00:00"))
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            if end < datetime.now(UTC):
                # Check if any sub-market still has future end_date
                has_future = any(
                    m.resolution_time and m.resolution_time > datetime.now(UTC)
                    for m in markets
                )
                if not has_future:
                    return "All sub-markets expired"
        except (ValueError, TypeError):
            pass

    # Noise check (event title)
    if matches_any(ev.title, ["5 min", "1 min", "5min", "1min"]):
        return "Noise event"

    # Time window checks — based on nearest active sub-market resolution
    now = datetime.now(UTC)
    future_markets = [m for m in markets if m.resolution_time and m.resolution_time > now]
    if future_markets:
        nearest_days = min((m.resolution_time - now).total_seconds() / 86400 for m in future_markets)

        # > 60 days: not in trading window yet
        if nearest_days > 60:
            return f"Too far from resolution ({nearest_days:.0f}d > 60d)"

        # > 30 days + all extreme probability: direction decided, no trade value
        if nearest_days > 30:
            prices = [m.yes_price for m in future_markets if m.yes_price and m.yes_price > 0]
            if prices and all(p > 0.85 or p < 0.15 for p in prices):
                return f"Far resolution ({nearest_days:.0f}d) + all extreme probability"

    return None


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

    # v0.5.0: binary market filter removed — multi-outcome markets now pass through

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
