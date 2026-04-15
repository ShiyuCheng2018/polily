"""Shared CLOB data fetching — single source of truth for market data.

Fetches 4 endpoints per token:
  /book      → depth (bids/asks)
  /midpoint  → yes_price
  /price BUY → best_bid (buy-side of order book)
  /price SELL→ best_ask (sell-side of order book)

Used by both poll (daemon/poll_job.py) and scan (scan/pipeline.py) paths.
"""

import asyncio
import json
import logging

import httpx

CLOB_BASE = "https://clob.polymarket.com"

logger = logging.getLogger(__name__)


async def fetch_clob_market_data(
    client: httpx.AsyncClient,
    token_id: str,
) -> dict:
    """Fetch all market data for one token from CLOB API.

    Raises httpx.HTTPStatusError if /book fails (e.g. 404 = market closed).

    Returns dict with keys:
        yes_price, no_price, last_trade_price  (from /midpoint, None on failure)
        best_bid, best_ask, spread             (from /price, None on failure)
        bid_depth, ask_depth, book_bids, book_asks  (from /book)
    """
    book_task = client.get(
        f"{CLOB_BASE}/book", params={"token_id": token_id},
    )
    mid_task = _fetch_midpoint(client, token_id)
    price_task = _fetch_prices(client, token_id)

    book_resp, midpoint, prices = await asyncio.gather(
        book_task, mid_task, price_task,
    )

    # /book — must succeed (raises on 4xx/5xx)
    book_resp.raise_for_status()
    book = book_resp.json()

    bids = book.get("bids", [])
    asks = book.get("asks", [])

    bid_depth = sum(float(b["size"]) for b in bids)
    ask_depth = sum(float(a["size"]) for a in asks)

    # Build result
    result = {
        "yes_price": midpoint,
        "no_price": round(1 - midpoint, 4) if midpoint is not None else None,
        "last_trade_price": midpoint,
        "best_bid": prices[0],   # /price SELL
        "best_ask": prices[1],   # /price BUY
        "spread": (
            round(prices[1] - prices[0], 4)
            if prices[0] is not None and prices[1] is not None
            else None
        ),
        "bid_depth": bid_depth,
        "ask_depth": ask_depth,
        "book_bids": json.dumps(
            [{"price": float(b["price"]), "size": float(b["size"])} for b in bids],
        ),
        "book_asks": json.dumps(
            [{"price": float(a["price"]), "size": float(a["size"])} for a in asks],
        ),
    }

    return result


async def _fetch_midpoint(
    client: httpx.AsyncClient, token_id: str,
) -> float | None:
    """Fetch /midpoint. Returns YES price or None on failure."""
    try:
        resp = await client.get(
            f"{CLOB_BASE}/midpoint", params={"token_id": token_id},
        )
        if resp.status_code == 200:
            mid = resp.json().get("mid")
            return float(mid) if mid is not None else None
    except Exception as e:
        logger.debug("Midpoint fetch failed for %s: %s", token_id[:20], e)
    return None


async def _fetch_prices(
    client: httpx.AsyncClient, token_id: str,
) -> tuple[float | None, float | None]:
    """Fetch /price BUY and /price SELL concurrently.

    Returns (best_bid, best_ask) — both None on failure.
    /price?side=BUY  = buy-side of the book = best_bid
    /price?side=SELL = sell-side of the book = best_ask
    """
    try:
        buy_resp, sell_resp = await asyncio.gather(
            client.get(
                f"{CLOB_BASE}/price",
                params={"token_id": token_id, "side": "BUY"},
            ),
            client.get(
                f"{CLOB_BASE}/price",
                params={"token_id": token_id, "side": "SELL"},
            ),
        )
        best_bid = float(buy_resp.json().get("price", 0)) if buy_resp.status_code == 200 else None
        best_ask = float(sell_resp.json().get("price", 0)) if sell_resp.status_code == 200 else None
        return best_bid, best_ask
    except Exception as e:
        logger.debug("Price fetch failed for %s: %s", token_id[:20], e)
        return None, None
