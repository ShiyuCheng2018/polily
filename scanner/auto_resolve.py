"""Auto-resolve paper trades by checking Polymarket market resolution status.

Uses PolilyDB and paper_store for trade management.
"""

import json
import logging

import httpx

from scanner.core.paper_store import get_open_trades, resolve_trade

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"


async def fetch_market_status(market_id: str) -> dict | None:
    """Fetch market resolution status from Gamma API."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"{GAMMA_BASE}/markets/{market_id}")
        resp.raise_for_status()
        return resp.json()


def _determine_result(market_data: dict) -> str | None:
    """Determine resolution result from market data.

    Returns "yes" if YES won, "no" if NO won, None if not resolved.
    """
    if not market_data.get("resolved") and not market_data.get("closed"):
        return None

    prices_raw = market_data.get("outcomePrices", "[]")
    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else (prices_raw or [])
    prices = [float(p) for p in prices]

    if len(prices) >= 2:
        # After resolution: winning outcome price -> 1.0, losing -> 0.0
        if prices[0] >= 0.95:
            return "yes"
        elif prices[1] >= 0.95:
            return "no"

    return None


async def auto_resolve_trades(db) -> int:
    """Check all open paper trades and resolve any that have settled.

    Returns count of newly resolved trades.
    """
    open_trades = get_open_trades(db)
    if not open_trades:
        return 0

    resolved_count = 0
    for trade in open_trades:
        market_id = trade["market_id"]
        try:
            market_data = await fetch_market_status(market_id)
            if market_data is None:
                continue

            result = _determine_result(market_data)
            if result is None:
                continue

            resolve_trade(trade["id"], result=result, db=db)
            logger.info(
                "Auto-resolved trade %s (market %s) -> %s",
                trade["id"], market_id, result,
            )
            resolved_count += 1
        except Exception:
            logger.exception("Failed to resolve trade %s (market %s)", trade["id"], market_id)

    return resolved_count
