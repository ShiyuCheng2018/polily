"""Polymarket taker fee computation.

Formula: fee = shares × feeRate × price × (1 - price)

POC-verified 2026-04-17. Reference: https://docs.polymarket.com/trading/fees
"""
from __future__ import annotations

from typing import Final

CATEGORY_FEE_RATES: Final[dict[str, float]] = {
    "Crypto": 0.072,
    "Sports": 0.03,
    "Finance": 0.04,
    "Politics": 0.04,
    "Tech": 0.04,
    "Mentions": 0.04,
    "Economics": 0.05,
    "Culture": 0.05,
    "Weather": 0.05,
    "Other": 0.05,
    "Geopolitics": 0.0,
    "World Events": 0.0,
}

_DEFAULT_RATE: Final[float] = 0.05


def calculate_taker_fee(shares: float, price: float, category: str | None) -> float:
    """Polymarket taker fee: quadratic curve peaked at p=0.5.

    Args:
        shares: number of shares traded (positive)
        price: execution price, 0 < price < 1
        category: Polymarket category; falls back to Other (0.05) if unknown/None

    Returns:
        Fee in USD, rounded to 4 decimals. Zero for Geopolitics/World Events or edge prices.
    """
    if shares <= 0 or price <= 0 or price >= 1:
        return 0.0
    rate = CATEGORY_FEE_RATES.get(category or "", _DEFAULT_RATE)
    return round(shares * rate * price * (1 - price), 4)
