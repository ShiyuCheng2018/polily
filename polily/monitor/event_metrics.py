"""Event-level metrics for negRisk (multi-outcome) events.

Pure math, no I/O. All metrics are computed from current sub-market
YES prices, optionally compared against previous prices.
"""
import math
from dataclasses import dataclass


@dataclass
class EventMetrics:
    """Computed metrics for a negRisk event."""

    overround: float  # sum(yes_prices) - 1
    entropy: float  # normalized Shannon entropy [0, 1]
    leader_id: str  # market_id with highest yes_price
    leader_margin: float  # p1 - p2
    leader_changed: bool  # leader swapped vs previous
    tv_distance: float  # total variation distance vs previous
    hhi: float  # Herfindahl-Hirschman index
    dutch_book_gap: float  # 1 - sum(best_ask), > 0 = arb


def compute_event_metrics(
    prices: dict[str, float],
    *,
    prev_prices: dict[str, float] | None = None,
    asks: dict[str, float] | None = None,
) -> EventMetrics:
    """Compute all event-level metrics from sub-market YES prices."""

    # Sort by price descending
    sorted_markets = sorted(prices.items(), key=lambda x: x[1], reverse=True)

    leader_id = sorted_markets[0][0]
    p1 = sorted_markets[0][1]
    p2 = sorted_markets[1][1] if len(sorted_markets) > 1 else 0.0
    leader_margin = p1 - p2

    # Overround
    overround = sum(prices.values()) - 1.0

    # Normalized Shannon entropy
    total = sum(prices.values())
    if total > 0 and len(prices) > 1:
        probs = [p / total for p in prices.values() if p > 0]
        raw_entropy = -sum(p * math.log(p) for p in probs)
        max_entropy = math.log(len(prices))
        entropy = raw_entropy / max_entropy if max_entropy > 0 else 0.0
    else:
        entropy = 0.0

    # HHI
    if total > 0:
        hhi = sum((p / total) ** 2 for p in prices.values())
    else:
        hhi = 0.0

    # Leader changed
    leader_changed = False
    tv_distance = 0.0
    if prev_prices:
        prev_sorted = sorted(
            prev_prices.items(), key=lambda x: x[1], reverse=True
        )
        prev_leader = prev_sorted[0][0]
        leader_changed = leader_id != prev_leader

        # TV distance
        all_ids = set(prices) | set(prev_prices)
        tv_distance = 0.5 * sum(
            abs(prices.get(mid, 0) - prev_prices.get(mid, 0))
            for mid in all_ids
        )

    # Dutch book gap
    dutch_book_gap = 0.0
    if asks:
        dutch_book_gap = 1.0 - sum(asks.values())

    return EventMetrics(
        overround=overround,
        entropy=entropy,
        leader_id=leader_id,
        leader_margin=leader_margin,
        leader_changed=leader_changed,
        tv_distance=tv_distance,
        hhi=hhi,
        dutch_book_gap=dutch_book_gap,
    )
