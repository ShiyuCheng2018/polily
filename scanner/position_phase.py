"""Position phase calculation — rule-based status labels for open trades."""


PHASE_LABELS = {
    "early": "起步",
    "working": "运行中",
    "take_profit": "止盈区",
    "high_risk": "高风险",
    "invalidated": "已失效",
}


def compute_position_phase(
    entry_price: float,
    current_price: float,
    side: str,
    days_held: float,
    days_to_resolution: float | None = None,
) -> str:
    """Compute position phase based on price movement and timing.

    Returns: early / working / take_profit / high_risk / invalidated
    """
    side = side.lower()
    if side not in ("yes", "no"):
        return "invalidated"
    if entry_price <= 0 or current_price < 0:
        return "invalidated"

    # Calculate PnL percentage based on side
    if side == "yes":
        pnl_pct = (current_price - entry_price) / entry_price
    else:
        # NO side: profit when price goes down
        if entry_price < 1:
            pnl_pct = (entry_price - current_price) / (1 - entry_price) if (1 - entry_price) > 0 else 0
        else:
            pnl_pct = 0

    # Early: just opened, not much movement
    if days_held < 1 and abs(pnl_pct) < 0.05:
        return "early"

    # Take profit zone: significant profit + near resolution
    if pnl_pct > 0.20 and days_to_resolution is not None and days_to_resolution < 3:
        return "take_profit"

    # Take profit: large profit regardless of time
    if pnl_pct > 0.40:
        return "take_profit"

    # High risk: significant loss
    if pnl_pct < -0.15:
        return "high_risk"

    # Working: in profit, thesis intact
    if pnl_pct > 0:
        return "working"

    # Slightly underwater but not critical
    if pnl_pct > -0.15:
        return "working"

    return "high_risk"
