"""Polymarket API client: Gamma (market discovery) + CLOB (order book)."""

import json
import logging
from datetime import UTC, datetime

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from scanner.config import ApiConfig
from scanner.models import BookLevel, Market

logger = logging.getLogger(__name__)

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def parse_gamma_event(event_data: dict) -> list[Market]:
    """Parse a Gamma API event response into Market objects.

    Handles JSON-string fields (outcomePrices, outcomes, clobTokenIds).
    """
    event_id = event_data.get("id")
    event_slug = event_data.get("slug")
    event_oi = event_data.get("openInterest")
    tags_raw = event_data.get("tags", [])
    tags = [t["label"] for t in tags_raw if isinstance(t, dict) and "label" in t]

    now = datetime.now(UTC)
    markets = []

    for md in event_data.get("markets", []):
        try:
            market = _parse_single_market(md, event_id, event_slug, event_oi, tags, now)
            markets.append(market)
        except (ValueError, KeyError, json.JSONDecodeError, TypeError) as e:
            logger.warning("Skipping malformed market %s: %s", md.get("id", "?"), e)
            continue

    # Compute multi-outcome prices sum for the event
    if len(markets) > 1:
        prices_sum = sum(m.yes_price for m in markets if m.yes_price is not None)
        for m in markets:
            m.event_outcome_prices_sum = prices_sum

    return markets


def _parse_single_market(
    md: dict, event_id: str | None, event_slug: str | None,
    event_oi: float | None, tags: list[str], now: datetime,
) -> Market:
    """Parse a single market dict from Gamma API response."""
    # Parse JSON string fields
    outcomes_raw = md.get("outcomes", "[]")
    outcomes = json.loads(outcomes_raw) if isinstance(outcomes_raw, str) else outcomes_raw

    prices_raw = md.get("outcomePrices", "[]")
    prices = json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
    prices = [float(p) for p in prices]

    yes_price = prices[0] if len(prices) > 0 else None
    no_price = prices[1] if len(prices) > 1 else None

    # Parse clobTokenIds for CLOB API order book queries
    token_ids_raw = md.get("clobTokenIds", "[]")
    token_ids = json.loads(token_ids_raw) if isinstance(token_ids_raw, str) else (token_ids_raw or [])
    clob_token_id_yes = token_ids[0] if len(token_ids) > 0 else None
    clob_token_id_no = token_ids[1] if len(token_ids) > 1 else None

    # Parse timestamps
    resolution_time = _parse_iso(md.get("endDate"))
    created_at = _parse_iso(md.get("createdAt"))
    updated_at = _parse_iso(md.get("updatedAt"))

    market = Market(
        market_id=md.get("id", ""),
        event_id=event_id,
        event_slug=event_slug,
        market_slug=md.get("slug"),
        title=md.get("question", ""),
        description=md.get("description"),
        rules=md.get("description"),  # Gamma embeds rules in description
        resolution_source=md.get("resolutionSource"),
        category=None,  # Gamma uses tags, not category
        tags=tags,
        outcomes=outcomes,
        yes_price=yes_price,
        no_price=no_price,
        clob_token_id_yes=clob_token_id_yes,
        clob_token_id_no=clob_token_id_no,
        best_bid_yes=md.get("bestBid"),
        best_ask_yes=md.get("bestAsk"),
        spread_yes=md.get("spread"),
        volume=md.get("volumeNum"),
        open_interest=event_oi,
        resolution_time=resolution_time,
        created_at=created_at,
        updated_at=updated_at,
        data_fetched_at=now,
    )
    return market


def parse_clob_book(book_data: dict) -> tuple[list[BookLevel], list[BookLevel]]:
    """Parse a CLOB /book response into bid and ask BookLevel lists.

    Returns (bids sorted descending by price, asks sorted ascending by price).
    """
    bids = [
        BookLevel(price=float(b["price"]), size=float(b["size"]))
        for b in book_data.get("bids", [])
    ]
    asks = [
        BookLevel(price=float(a["price"]), size=float(a["size"]))
        for a in book_data.get("asks", [])
    ]
    bids.sort(key=lambda x: x.price, reverse=True)
    asks.sort(key=lambda x: x.price)
    return bids, asks


class PolymarketClient:
    """Async client for Polymarket Gamma + CLOB APIs."""

    def __init__(self, config: ApiConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.request_timeout_seconds),
                headers={"User-Agent": self.config.user_agent},
            )
        return self._client

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1.5, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
    )
    async def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        client = await self._get_client()
        response = await client.get(url, params=params)
        response.raise_for_status()
        return response

    async def fetch_events(
        self,
        limit: int = 100,
        offset: int = 0,
        order: str = "volume24hr",
        ascending: bool = False,
    ) -> list[dict]:
        """Fetch events from Gamma API."""
        response = await self._get(
            f"{GAMMA_BASE}/events",
            params={
                "active": "true",
                "closed": "false",
                "limit": limit,
                "offset": offset,
                "order": order,
                "ascending": str(ascending).lower(),
            },
        )
        return response.json()

    async def fetch_all_events(self, max_events: int = 500) -> list[dict]:
        """Fetch events paginated, up to max_events."""
        all_events = []
        offset = 0
        page_size = 100

        while len(all_events) < max_events:
            events = await self.fetch_events(limit=page_size, offset=offset)
            if not events:
                break
            all_events.extend(events)
            offset += page_size

        return all_events[:max_events]

    async def fetch_book(self, token_id: str) -> tuple[list[BookLevel], list[BookLevel]]:
        """Fetch order book for a token from CLOB API."""
        response = await self._get(
            f"{CLOB_BASE}/book",
            params={"token_id": token_id},
        )
        return parse_clob_book(response.json())

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
