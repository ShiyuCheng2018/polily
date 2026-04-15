"""Order book depth analysis: slippage simulation, imbalance, staleness detection."""

from dataclasses import dataclass

from scanner.core.models import BookLevel


@dataclass
class OrderBookAnalysis:
    total_bid_depth: float
    total_ask_depth: float
    slippage_avg_price: float | None
    slippage_pct: float | None
    imbalance_ratio: float | None
    is_stale: bool


def compute_slippage(
    levels: list[BookLevel],
    order_size_usd: float,
) -> tuple[float | None, float | None]:
    """Simulate filling an order against book levels.

    Returns (avg_fill_price, slippage_pct relative to best price).
    For buy orders, pass ask levels. For sell orders, pass bid levels.
    """
    if not levels:
        return None, None
    if order_size_usd <= 0:
        return levels[0].price, 0.0

    best_price = levels[0].price
    remaining = order_size_usd
    total_cost = 0.0

    for level in levels:
        fill_at_level = min(remaining, level.size)
        total_cost += fill_at_level * level.price
        remaining -= fill_at_level
        if remaining <= 0:
            break

    if remaining > 0:
        # Order exceeds total book depth; fill rest at worst price
        total_cost += remaining * levels[-1].price

    filled = order_size_usd
    avg_price = total_cost / filled
    slippage_pct = (avg_price - best_price) / best_price if best_price > 0 else 0.0

    return avg_price, slippage_pct


def compute_depth_imbalance(
    bids: list[BookLevel],
    asks: list[BookLevel],
) -> float | None:
    """Compute bid/ask depth ratio. >1 means bid-heavy, <1 means ask-heavy."""
    total_bid = sum(level.size for level in bids)
    total_ask = sum(level.size for level in asks)
    if total_ask == 0:
        return None
    return total_bid / total_ask


def analyze_book(
    bids: list[BookLevel],
    asks: list[BookLevel],
    order_size_usd: float = 20.0,
) -> OrderBookAnalysis:
    """Run full order book analysis."""
    total_bid = sum(level.size for level in bids)
    total_ask = sum(level.size for level in asks)

    avg_price, slippage_pct = compute_slippage(asks, order_size_usd)
    imbalance = compute_depth_imbalance(bids, asks)

    return OrderBookAnalysis(
        total_bid_depth=total_bid,
        total_ask_depth=total_ask,
        slippage_avg_price=avg_price,
        slippage_pct=slippage_pct,
        imbalance_ratio=imbalance,
        is_stale=not bids or not asks,
    )
