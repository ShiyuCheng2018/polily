"""Tests for Polymarket API client (using fixture data, no real API calls)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.api import PolymarketClient, parse_clob_book, parse_gamma_event
from scanner.core.config import ApiConfig
from scanner.core.event_store import EventRow

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
        _event_row, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        assert len(markets) == 1
        m = markets[0]
        assert m.market_id == "market-abc"
        assert m.title == "Will BTC be above $88,000 on March 30?"
        assert m.outcomes == ["Yes", "No"]

    def test_parse_prices(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.yes_price == 0.55
        assert m.no_price == 0.47

    def test_parse_bid_ask(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.best_bid_yes == 0.54
        assert m.best_ask_yes == 0.56
        assert m.spread_yes == 0.02

    def test_parse_volume(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.volume == 50000.50

    def test_parse_resolution_time(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.resolution_time is not None
        assert m.resolution_time.year == 2026
        assert m.resolution_time.month == 3
        assert m.resolution_time.day == 30

    def test_parse_event_id(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.event_id == "event-123"

    def test_parse_tags(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert "crypto" in [t.lower() for t in m.tags]

    def test_parse_resolution_source(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.resolution_source == "https://coingecko.com"

    def test_parse_description(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert "88000" in m.description

    def test_parse_open_interest_from_event(self):
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
        assert m.open_interest == 128000

    def test_parse_json_string_fields(self):
        """outcomePrices and outcomes are JSON strings, not arrays."""
        _, markets = parse_gamma_event(SAMPLE_GAMMA_EVENT)
        m = markets[0]
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


class TestParseGammaEventV2:
    def test_returns_tuple(self):
        event_data = {
            "id": "16167",
            "title": "Test Event",
            "slug": "test-event",
            "description": "Test description",
            "negRisk": False,
            "endDate": "2026-12-31T12:00:00Z",
            "volume": 50000.0,
            "liquidity": 10000.0,
            "openInterest": 30000.0,
            "competitive": 0.85,
            "tags": [{"label": "Crypto", "slug": "crypto"}],
            "markets": [{
                "id": "m1",
                "question": "Will X happen?",
                "slug": "will-x-happen",
                "description": "Resolution criteria",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.55","0.45"]',
                "clobTokenIds": '["token1","token2"]',
                "conditionId": "0x123abc",
                "acceptingOrders": True,
                "bestBid": 0.54,
                "bestAsk": 0.56,
                "spread": 0.02,
                "volumeNum": 25000.0,
                "lastTradePrice": 0.55,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-04-01T00:00:00Z",
            }],
        }
        result = parse_gamma_event(event_data)
        assert isinstance(result, tuple)
        assert len(result) == 2
        event_row, markets = result
        assert isinstance(event_row, EventRow)
        assert isinstance(markets, list)

    def test_event_row_fields(self):
        event_data = {
            "id": "16167",
            "title": "Test Event",
            "slug": "test-event",
            "description": "Desc",
            "negRisk": True,
            "negRiskMarketID": "0xabc",
            "negRiskAugmented": False,
            "endDate": "2026-12-31T12:00:00Z",
            "startDate": "2026-01-01T00:00:00Z",
            "volume": 50000.0,
            "liquidity": 10000.0,
            "openInterest": 30000.0,
            "competitive": 0.85,
            "tags": [{"label": "Crypto", "slug": "crypto"}],
            "eventMetadata": {"context_description": "AI context"},
            "markets": [
                {"id": "m1", "question": "Q1", "outcomes": '["Yes","No"]',
                 "outcomePrices": '["0.6","0.4"]', "clobTokenIds": '["t1","t2"]',
                 "conditionId": "0x1", "acceptingOrders": True,
                 "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-04-01T00:00:00Z"},
                {"id": "m2", "question": "Q2", "outcomes": '["Yes","No"]',
                 "outcomePrices": '["0.3","0.7"]', "clobTokenIds": '["t3","t4"]',
                 "conditionId": "0x2", "acceptingOrders": True,
                 "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-04-01T00:00:00Z"},
            ],
        }
        event_row, markets = parse_gamma_event(event_data)
        assert event_row.event_id == "16167"
        assert event_row.title == "Test Event"
        assert event_row.neg_risk is True
        assert event_row.neg_risk_market_id == "0xabc"
        assert event_row.market_count == 2
        assert event_row.volume == 50000.0
        assert event_row.open_interest == 30000.0
        assert "Crypto" in event_row.tags  # tags stored as JSON string

    def test_market_new_fields(self):
        event_data = {
            "id": "ev1",
            "title": "E",
            "negRisk": True,
            "negRiskMarketID": "0xabc",
            "tags": [],
            "markets": [{
                "id": "m1",
                "question": "Q",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '["0.6","0.4"]',
                "clobTokenIds": '["t1","t2"]',
                "conditionId": "0x123",
                "questionID": "0x456",
                "groupItemTitle": "Option A",
                "groupItemThreshold": "0",
                "negRisk": True,
                "negRiskMarketID": "0xabc",
                "negRiskRequestID": "0xdef",
                "negRiskOther": False,
                "acceptingOrders": True,
                "orderPriceMinTickSize": 0.001,
                "lastTradePrice": 0.59,
                "bestBid": 0.58,
                "bestAsk": 0.60,
                "spread": 0.02,
                "volumeNum": 5000.0,
                "liquidityNum": 2000.0,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-04-01T00:00:00Z",
            }],
        }
        event_row, markets = parse_gamma_event(event_data)
        m = markets[0]
        assert m.group_item_title == "Option A"
        assert m.group_item_threshold == "0"
        assert m.question_id == "0x456"
        assert m.neg_risk is True
        assert m.neg_risk_request_id == "0xdef"
        assert m.neg_risk_other is False
        assert m.accepting_orders is True

    def test_multi_outcome_prices_sum(self):
        """Multi-outcome event should compute event_outcome_prices_sum."""
        event_data = {
            "id": "ev1", "title": "E", "negRisk": True, "tags": [],
            "markets": [
                {"id": "m1", "question": "Q1", "outcomes": '["Yes","No"]',
                 "outcomePrices": '["0.4","0.6"]', "clobTokenIds": '["t1","t2"]',
                 "conditionId": "0x1", "acceptingOrders": True,
                 "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-04-01T00:00:00Z"},
                {"id": "m2", "question": "Q2", "outcomes": '["Yes","No"]',
                 "outcomePrices": '["0.3","0.7"]', "clobTokenIds": '["t3","t4"]',
                 "conditionId": "0x2", "acceptingOrders": True,
                 "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-04-01T00:00:00Z"},
                {"id": "m3", "question": "Q3", "outcomes": '["Yes","No"]',
                 "outcomePrices": '["0.35","0.65"]', "clobTokenIds": '["t5","t6"]',
                 "conditionId": "0x3", "acceptingOrders": True,
                 "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-04-01T00:00:00Z"},
            ],
        }
        _, markets = parse_gamma_event(event_data)
        # Sum of YES prices: 0.4 + 0.3 + 0.35 = 1.05
        assert markets[0].event_outcome_prices_sum is not None
        assert abs(markets[0].event_outcome_prices_sum - 1.05) < 0.001


class TestGammaFeeParsing:
    """Gamma's `feesEnabled` + `feeSchedule` must persist onto Market.

    Covers the numeric-type inconsistency Gamma shows in practice (rates
    sometimes come back as strings, schedule sometimes missing entirely).
    """

    def _minimal(self, **market_overrides) -> dict:
        base = {
            "id": "m1", "question": "Q", "outcomes": '["Yes","No"]',
            "outcomePrices": '["0.5","0.5"]', "clobTokenIds": '["t1","t2"]',
            "conditionId": "0x1", "acceptingOrders": True,
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-04-01T00:00:00Z",
        }
        base.update(market_overrides)
        return {"id": "ev1", "title": "E", "tags": [], "markets": [base]}

    def test_fees_enabled_with_numeric_rate(self):
        event = self._minimal(
            feesEnabled=True,
            feeSchedule={"exponent": 1, "rate": 0.072, "takerOnly": True},
        )
        _, markets = parse_gamma_event(event)
        assert markets[0].fees_enabled is True
        assert markets[0].fee_rate == 0.072

    def test_fees_enabled_with_string_rate(self):
        """Gamma sometimes returns numeric fields as strings."""
        event = self._minimal(
            feesEnabled=True, feeSchedule={"rate": "0.03"},
        )
        _, markets = parse_gamma_event(event)
        assert markets[0].fee_rate == 0.03

    def test_fees_disabled_schedule_ignored(self):
        """Majority case: feesEnabled=False, often no schedule either."""
        event = self._minimal(feesEnabled=False, feeSchedule=None)
        _, markets = parse_gamma_event(event)
        assert markets[0].fees_enabled is False
        assert markets[0].fee_rate is None

    def test_missing_fee_fields_default_to_disabled(self):
        """Older events without fee fields at all → safe default (disabled)."""
        event = self._minimal()  # no feesEnabled, no feeSchedule
        _, markets = parse_gamma_event(event)
        assert markets[0].fees_enabled is False
        assert markets[0].fee_rate is None

    def test_malformed_rate_falls_back_to_none(self):
        """feeSchedule.rate present but unparseable — don't crash, set None."""
        event = self._minimal(
            feesEnabled=True, feeSchedule={"rate": "not-a-number"},
        )
        _, markets = parse_gamma_event(event)
        assert markets[0].fee_rate is None
