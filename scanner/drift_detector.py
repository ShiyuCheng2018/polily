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
