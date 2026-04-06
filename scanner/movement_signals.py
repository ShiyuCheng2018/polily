"""Pure-math signal calculators for movement detection.

All functions use Python stdlib only (statistics module).
No numpy, no pandas, no external dependencies.
"""

import math
import statistics


def compute_price_z_score(current_price: float, price_history: list[float]) -> float:
    """Z-score of current price vs rolling history.

    Returns 0.0 if insufficient data or zero std dev.
    """
    if len(price_history) < 2:
        return 0.0
    try:
        mean = statistics.mean(price_history)
        std = statistics.stdev(price_history)
        if std == 0:
            return 0.0
        return (current_price - mean) / std
    except statistics.StatisticsError:
        return 0.0


def compute_volume_ratio(recent_volume: float, baseline_volume: float) -> float:
    """Ratio of recent volume to baseline average.

    Returns 0.0 if no baseline.
    """
    if baseline_volume <= 0:
        return 0.0
    return recent_volume / baseline_volume


def compute_book_imbalance(bid_depth: float, ask_depth: float) -> float:
    """Bid-ask imbalance: (bid - ask) / (bid + ask).

    Positive = bid-heavy (buying pressure).
    Negative = ask-heavy (selling pressure).
    """
    total = bid_depth + ask_depth
    if total <= 0:
        return 0.0
    return (bid_depth - ask_depth) / total


def compute_trade_concentration(trade_sizes: list[float]) -> float:
    """Max single trade as fraction of total volume.

    High concentration = whale move.
    Low concentration = dispersed/consensus.
    """
    if not trade_sizes:
        return 0.0
    total = sum(trade_sizes)
    if total <= 0:
        return 0.0
    return max(trade_sizes) / total


def compute_open_interest_delta(current_oi: float, previous_oi: float) -> float:
    """Relative change in open interest.

    Positive = new money entering.
    Negative = positions closing.
    """
    if previous_oi <= 0:
        return 0.0
    return (current_oi - previous_oi) / previous_oi


# --- Market-type-specific signals ---


def compute_fair_value_divergence(market_price: float, fair_value: float) -> float:
    """Absolute divergence between market odds and model fair value.

    Used for crypto threshold markets where we have a Black-Scholes fair value.
    """
    return abs(market_price - fair_value)


def compute_underlying_z_score(current_price: float, price_history: list[float]) -> float:
    """Z-score for the underlying asset (e.g. BTC price).

    Delegates to compute_price_z_score — same math, different data.
    """
    return compute_price_z_score(current_price, price_history)


def compute_cross_divergence(underlying_move_pct: float, odds_move_pct: float) -> float:
    """Divergence between underlying asset movement and odds movement.

    High value = one moved but the other didn't => potential opportunity.
    Returns 0-1 normalized.
    """
    if underlying_move_pct == 0 and odds_move_pct == 0:
        return 0.0
    total = abs(underlying_move_pct) + abs(odds_move_pct)
    if total == 0:
        return 0.0
    diff = abs(abs(underlying_move_pct) - abs(odds_move_pct))
    return min(diff / total, 1.0)


def compute_sustained_drift(price_series: list[float]) -> float:
    """Measure how consistently prices drift in one direction.

    Returns 0-1: 1.0 = all steps in same direction, 0.0 = alternating.
    Used for political markets where info is digested gradually.
    """
    if len(price_series) < 2:
        return 0.0
    steps = [price_series[i] - price_series[i - 1] for i in range(1, len(price_series))]
    if not steps:
        return 0.0
    positive = sum(1 for s in steps if s > 0)
    negative = sum(1 for s in steps if s < 0)
    dominant = max(positive, negative)
    return dominant / len(steps)


def compute_time_decay_adjusted_move(price_change_pct: float, days_to_event: float) -> float:
    """Adjust price change significance based on proximity to event.

    Same price change means more when closer to the event.
    """
    if days_to_event <= 0:
        return 0.0
    if price_change_pct == 0:
        return 0.0
    factor = math.sqrt(30.0 / max(days_to_event, 0.1))
    return abs(price_change_pct) * factor


def compute_volume_price_confirmation(price_change_pct: float, volume_ratio: float) -> float:
    """How well volume confirms the price move.

    Price up + volume up = confirmed (high score).
    Returns 0-1.
    """
    if price_change_pct == 0:
        return 0.0
    vol_signal = min(max(volume_ratio - 0.5, 0) / 4.0, 1.0)
    return vol_signal * min(abs(price_change_pct) * 20, 1.0)
