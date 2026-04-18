"""Polymarket taker fee computation.

Driven by per-market fields:
- `market.feesEnabled` — master gate (false → 0 fee, regardless of anything else)
- `market.feeSchedule.rate` — coefficient in the quadratic curve

Formula (when enabled):  fee = shares × rate × price × (1 - price)

The `feeSchedule.exponent` field is always 1 in observed Gamma responses
(crypto_fees_v2, sports_fees_v2), so we hardcode exp=1 here. If Polymarket
introduces a non-linear curve, the formula will need updating.

POC-verified 2026-04-18 against live Gamma (events/357807 Iran disabled,
markets/2013686 BTC Up-or-Down enabled with rate=0.072).

Reference: https://docs.polymarket.com/trading/fees
"""

from __future__ import annotations


def calculate_taker_fee(
    *,
    shares: float,
    price: float,
    fees_enabled: bool,
    fee_rate: float | None,
) -> float:
    """Quadratic taker fee, gated on Polymarket's market.feesEnabled flag.

    Args:
        shares: shares traded, must be positive (0 or negative → 0 fee).
        price: execution price, must be in (0, 1) exclusive. Edge prices
            mean the market is effectively resolved → 0 fee.
        fees_enabled: mirrors `market.feesEnabled` from Gamma. If False,
            no fee is ever charged on this market, regardless of other
            fields. This is the authoritative gate — don't second-guess.
        fee_rate: mirrors `market.feeSchedule.rate` from Gamma. None when
            the market has no fee schedule (degenerate case, treated as 0).

    Returns:
        Fee in USD, rounded to 4 decimals.
    """
    if not fees_enabled or fee_rate is None:
        return 0.0
    if shares <= 0 or price <= 0 or price >= 1:
        return 0.0
    return round(shares * fee_rate * price * (1 - price), 4)
