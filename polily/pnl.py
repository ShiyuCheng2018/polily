"""P&L calculation — pure functions, no side effects."""


def calc_unrealized_pnl(
    side: str, entry_price: float, current_price: float, position_size_usd: float,
) -> dict:
    """Calculate unrealized P&L for an open position.

    Args:
        side: 'yes' or 'no'
        entry_price: price at entry (YES price if side=yes, NO price if side=no)
        current_price: current YES price from market
        position_size_usd: total position size in USD

    Returns dict with: shares, current_value, pnl, pnl_pct
    """
    if entry_price <= 0 or position_size_usd <= 0:
        return {"shares": 0, "current_value": 0, "pnl": 0, "pnl_pct": 0}

    shares = position_size_usd / entry_price
    if side == "no":
        cur = 1 - current_price  # NO price
    else:
        cur = current_price

    current_value = cur * shares
    pnl = current_value - position_size_usd
    pnl_pct = pnl / position_size_usd * 100

    return {
        "shares": round(shares, 1),
        "current_value": round(current_value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 1),
    }
