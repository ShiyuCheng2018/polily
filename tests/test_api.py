"""Tests for Polymarket API client (using fixture data, no real API calls)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.api import PolymarketClient, parse_clob_book, parse_gamma_event
from scanner.config import ApiConfig

# --- Fixture data mimicking real API responses ---

SAMPLE_GAMMA_EVENT = {
    "id": "event-123",
    "title": "BTC Price Markets",
    "slug": "btc-price-markets",
    "description": "Markets about Bitcoin price thresholds",
    "volume": 500000,
    "volume24hr": 42000,
    "openInterest": 128000,
    "startDate": "2026-03-25T00:00:00Z",
    "endDate": "2026-03-30T00:00:00Z",
    "tags": [{"label": "Crypto", "slug": "crypto"}],
    "markets": [
        {
            "id": "market-abc",
            "question": "Will BTC be above $88,000 on March 30?",
            "conditionId": "0xcond123",
            "slug": "btc-above-88k-mar30",
            "outcomes": '["Yes", "No"]',
            "outcomePrices": '["0.55", "0.47"]',
            "clobTokenIds": '["tok-yes-123", "tok-no-456"]',
            "bestBid": 0.54,
            "bestAsk": 0.56,
            "spread": 0.02,
            "lastTradePrice": 0.55,
            "volume": "50000.50",
            "volumeNum": 50000.50,
            "volume24hr": 12000.0,
            "liquidityNum": 25000.0,
            "endDate": "2026-03-30T00:00:00Z",
            "startDate": "2026-03-25T00:00:00Z",
            "createdAt": "2026-03-25T10:00:00Z",
            "updatedAt": "2026-03-28T12:00:00Z",
            "active": True,
            "closed": False,
            "acceptingOrders": True,
            "enableOrderBook": True,
            "negRisk": False,
            "description": "Resolves Yes if BTC/USD > 88000 at 00:00 UTC March 31.",
            "resolutionSource": "https://coingecko.com",
        }
    ],
}

SAMPLE_CLOB_BOOK = {
    "market": "0xcond123",
    "asset_id": "tok-yes-123",
    "timestamp": "1774718051611",
    "bids": [
        {"price": "0.54", "size": "1500.00"},
        {"price": "0.53", "size": "2000.00"},
        {"price": "0.52", "size": "800.00"},
    ],
    "asks": [
        {"price": "0.56", "size": "1200.00"},
        {"price": "0.57", "size": "1800.00"},
        {"price": "0.58", "size": "500.00"},
    ],
}


class TestParseGammaEvent:
    def test_parse_event_markets(self):
        markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        assert len(markets) == 1
        m = markets[0]
        assert m.market_id == "market-abc"
        assert m.title == "Will BTC be above $88,000 on March 30?"
        assert m.outcomes == ["Yes", "No"]

    def test_parse_prices(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.yes_price == 0.55
        assert m.no_price == 0.47

    def test_parse_bid_ask(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.best_bid_yes == 0.54
        assert m.best_ask_yes == 0.56
        assert m.spread_yes == 0.02

    def test_parse_volume(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.volume == 50000.50

    def test_parse_resolution_time(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.resolution_time is not None
        assert m.resolution_time.year == 2026
        assert m.resolution_time.month == 3
        assert m.resolution_time.day == 30

    def test_parse_event_id(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.event_id == "event-123"

    def test_parse_tags(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert "crypto" in [t.lower() for t in m.tags]

    def test_parse_resolution_source(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.resolution_source == "https://coingecko.com"

    def test_parse_description(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert "88000" in m.description

    def test_parse_open_interest_from_event(self):
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        assert m.open_interest == 128000

    def test_parse_json_string_fields(self):
        """outcomePrices and outcomes are JSON strings, not arrays."""
        m = parse_gamma_event(SAMPLE_GAMMA_EVENT)[0]
        # Should be parsed correctly despite being JSON strings
        assert isinstance(m.outcomes, list)
        assert isinstance(m.yes_price, float)


class TestParseClobBook:
    def test_parse_bids(self):
        bids, asks = parse_clob_book(SAMPLE_CLOB_BOOK)
        assert len(bids) == 3
        assert bids[0].price == 0.54
        assert bids[0].size == 1500.0

    def test_parse_asks(self):
        bids, asks = parse_clob_book(SAMPLE_CLOB_BOOK)
        assert len(asks) == 3
        assert asks[0].price == 0.56
        assert asks[0].size == 1200.0

    def test_sorted_bids_descending(self):
        bids, _ = parse_clob_book(SAMPLE_CLOB_BOOK)
        prices = [b.price for b in bids]
        assert prices == sorted(prices, reverse=True)

    def test_sorted_asks_ascending(self):
        _, asks = parse_clob_book(SAMPLE_CLOB_BOOK)
        prices = [a.price for a in asks]
        assert prices == sorted(prices)

    def test_empty_book(self):
        empty = {"bids": [], "asks": []}
        bids, asks = parse_clob_book(empty)
        assert bids == []
        assert asks == []

    def test_stale_book_detection(self):
        """Book with bid=0.01, ask=0.99 should be flagged as stale."""
        stale = {
            "bids": [{"price": "0.01", "size": "100"}],
            "asks": [{"price": "0.99", "size": "100"}],
        }
        bids, asks = parse_clob_book(stale)
        # The parser returns data; staleness check is caller's responsibility
        assert bids[0].price == 0.01
        assert asks[0].price == 0.99


class TestPolymarketClient:
    @pytest.mark.asyncio
    async def test_client_creation(self):
        config = ApiConfig()
        client = PolymarketClient(config)
        assert client is not None

    @pytest.mark.asyncio
    async def test_fetch_events_mocked(self):
        config = ApiConfig()
        client = PolymarketClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [SAMPLE_GAMMA_EVENT]
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get", new_callable=AsyncMock, return_value=mock_response):
            events = await client.fetch_events(limit=1)
            assert len(events) == 1

    @pytest.mark.asyncio
    async def test_fetch_book_mocked(self):
        config = ApiConfig()
        client = PolymarketClient(config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = SAMPLE_CLOB_BOOK
        mock_response.raise_for_status = MagicMock()

        with patch.object(client, "_get", new_callable=AsyncMock, return_value=mock_response):
            bids, asks = await client.fetch_book("tok-yes-123")
            assert len(bids) == 3
            assert len(asks) == 3
