"""Aggregation helper for WalletView's balance panel.

Pure function over snapshot + positions + price lookup. Kept out of the
view widget so the math is unit-testable without mounting Textual.
"""

from __future__ import annotations

from collections.abc import Callable


def compute_wallet_overview(
    *,
    snapshot: dict,
    positions: list[dict],
    price_lookup: Callable[[str, str], float | None],
) -> dict:
    """Roll up wallet + positions into a single display dict.

    Args:
        snapshot: output of `WalletService.get_snapshot()` — must include
            `cash_usd`, `starting_balance`, `topup_total`, `withdraw_total`,
            `cumulative_realized_pnl`.
        positions: output of `PositionManager.get_all_positions()`.
        price_lookup: callable `(market_id, side) -> yes_side_price_for_sell`.
            Returns None if the market price is unavailable — positions are
            then valued at cost basis (no unrealized P&L contribution).

    Returns:
        dict with keys:
            cash_usd, positions_market_value, equity,
            positions_cost_basis, unrealized_pnl, realized_pnl,
            starting_balance, topup_total, withdraw_total, net_inflow,
            total_pnl, roi_pct, open_positions_count
    """
    cash = float(snapshot.get("cash_usd", 0.0))
    starting = float(snapshot.get("starting_balance", 0.0))
    topup = float(snapshot.get("topup_total", 0.0))
    withdraw = float(snapshot.get("withdraw_total", 0.0))
    realized = float(snapshot.get("cumulative_realized_pnl", 0.0))

    market_value = 0.0
    cost_basis_total = 0.0
    for p in positions:
        shares = float(p["shares"])
        cost_basis_total += float(p["cost_basis"])
        price = price_lookup(p["market_id"], p["side"])
        if price is not None:
            market_value += shares * price
        else:
            # Unknown current price → value at cost (neutral contribution).
            market_value += float(p["cost_basis"])

    equity = cash + market_value
    unrealized = market_value - cost_basis_total
    net_inflow = starting + topup - withdraw
    total_pnl = equity - net_inflow
    roi_pct = (total_pnl / net_inflow * 100.0) if net_inflow > 0 else 0.0

    return {
        "cash_usd": cash,
        "positions_market_value": market_value,
        "equity": equity,
        "positions_cost_basis": cost_basis_total,
        "unrealized_pnl": unrealized,
        "realized_pnl": realized,
        "starting_balance": starting,
        "topup_total": topup,
        "withdraw_total": withdraw,
        "net_inflow": net_inflow,
        "total_pnl": total_pnl,
        "roi_pct": roi_pct,
        "open_positions_count": len(positions),
    }
