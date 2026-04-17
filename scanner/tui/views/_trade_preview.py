"""Pure computation helpers for TradeDialog Buy/Sell preview panels.

Extracted from the dialog so they can be unit-tested in <10ms without
mounting Textual widgets. All fee arithmetic delegates to
`scanner.core.fees.calculate_taker_fee` so the dialog preview matches
what `TradeEngine.execute_buy/sell` actually charges.
"""

from __future__ import annotations

from scanner.core.fees import calculate_taker_fee


def compute_buy_preview(
    *, amount_usd: float, price: float, category: str | None,
) -> dict:
    """Buy preview: USD amount → shares + fee + to-win payout.

    `to_win` mirrors Polymarket's "To win $X" convention: shares × $1
    (the per-share resolution payout when this outcome wins).
    """
    if amount_usd <= 0:
        raise ValueError(f"amount_usd must be positive, got {amount_usd}")
    if not 0 < price < 1:
        raise ValueError(f"price must be in (0, 1), got {price}")

    shares = amount_usd / price
    fee = calculate_taker_fee(shares, price, category)
    return {
        "shares": shares,
        "to_win": shares,  # each winning share pays $1
        "fee": fee,
        "cash_required": amount_usd + fee,
    }


def compute_sell_preview(
    *, shares: float, price: float, category: str | None, avg_cost: float,
) -> dict:
    """Sell preview: shares at exit price → proceeds + fee + realized P&L.

    `realized_pnl` formula `(price - avg_cost) × shares` matches the value
    returned by `TradeEngine.execute_sell` (before fees, per Polymarket's
    realized-P&L display convention).
    """
    if shares <= 0:
        raise ValueError(f"shares must be positive, got {shares}")

    proceeds = shares * price
    fee = calculate_taker_fee(shares, price, category)
    return {
        "proceeds": proceeds,
        "fee": fee,
        "net_received": proceeds - fee,
        "realized_pnl": (price - avg_cost) * shares,
    }


def shares_from_pct(*, holdings: float, pct: int) -> float:
    """Quick-pick helper: fraction of current holdings."""
    if not 0 < pct <= 100:
        raise ValueError(f"pct must be in (0, 100], got {pct}")
    return holdings * pct / 100
