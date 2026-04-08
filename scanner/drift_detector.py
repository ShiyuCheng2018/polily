"""Cumulative drift detection — rolling windows + CUSUM.

Complements per-tick magnitude/quality scoring by catching:
- Slow directional drift (12% over 2 hours in 1% increments)
- Post-sleep/wake price gaps
"""


def check_rolling_windows(
    current_price: float,
    price_history: list[tuple[int, float]],
    windows: dict[int, float],
) -> list[dict]:
    """Check price change over multiple rolling time windows.

    Args:
        current_price: current YES price
        price_history: [(seconds_ago, price), ...] — larger seconds_ago = older
        windows: {window_minutes: absolute_change_threshold}

    Returns list of triggered alerts.
    """
    if not price_history:
        return []

    alerts = []
    for window_min, threshold in windows.items():
        window_sec = window_min * 60
        # Find oldest entry within this window
        ref_price = None
        best_sec = -1
        for sec_ago, price in price_history:
            if sec_ago <= window_sec and sec_ago > best_sec:
                ref_price = price
                best_sec = sec_ago

        if ref_price is None:
            continue

        change = abs(current_price - ref_price)
        if change >= threshold:
            alerts.append({
                "type": "rolling_window",
                "window": window_min,
                "change": round(change, 4),
                "threshold": threshold,
                "direction": "UP" if current_price > ref_price else "DOWN",
            })

    return alerts


class CusumAccumulator:
    """CUSUM (Cumulative Sum) drift detector for a single market.

    Accumulates small directional price changes. Triggers when cumulative
    deviation exceeds threshold, filtering out noise via drift parameter.
    """

    def __init__(self, drift: float = 0.003, threshold: float = 0.06):
        self.drift = drift
        self.threshold = threshold
        self.s_pos = 0.0  # upward accumulator
        self.s_neg = 0.0  # downward accumulator

    def update(self, price_change: float) -> list[dict]:
        """Feed a tick-to-tick price change. Returns alerts if triggered."""
        self.s_pos = max(0, self.s_pos + price_change - self.drift)
        self.s_neg = max(0, self.s_neg - price_change - self.drift)

        alerts = []
        if self.s_pos > self.threshold:
            alerts.append({"type": "cusum", "direction": "UP", "cumulative": round(self.s_pos, 4)})
            self.s_pos = 0
        if self.s_neg > self.threshold:
            alerts.append({"type": "cusum", "direction": "DOWN", "cumulative": round(self.s_neg, 4)})
            self.s_neg = 0
        return alerts

    def warm_up(self, price_deltas: list[float]) -> None:
        """Replay historical tick deltas to restore state after restart."""
        for delta in price_deltas:
            self.update(delta)


def build_price_history(market_id: str, db, hours: int = 4) -> list[tuple[int, float]]:
    """Build (seconds_ago, price) pairs from movement_log.

    Returns list sorted by recency (smallest seconds_ago first).
    """
    from datetime import UTC, datetime

    from scanner.movement_store import get_recent_movements

    entries = get_recent_movements(market_id, db, hours=hours)
    now = datetime.now(UTC)
    result = []
    for e in entries:
        if e.get("yes_price") is None:
            continue
        ts = datetime.fromisoformat(e["created_at"])
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        sec_ago = int((now - ts).total_seconds())
        result.append((sec_ago, e["yes_price"]))
    return result
