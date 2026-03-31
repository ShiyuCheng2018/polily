"""Tests for two-pass scan: metadata fetch → filter → order book fetch → score."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.api import parse_clob_book
from scanner.config import ScannerConfig
from scanner.models import BookLevel
from scanner.pipeline import enrich_with_orderbook
from tests.conftest import make_market

SAMPLE_BOOK = {
    "bids": [
        {"price": "0.54", "size": "1500"},
        {"price": "0.53", "size": "2200"},
        {"price": "0.52", "size": "900"},
    ],
    "asks": [
        {"price": "0.56", "size": "1300"},
        {"price": "0.57", "size": "1800"},
        {"price": "0.58", "size": "600"},
    ],
}

STALE_BOOK = {
    "bids": [{"price": "0.01", "size": "100"}],
    "asks": [{"price": "0.99", "size": "100"}],
}


class TestEnrichWithOrderbook:
    @pytest.mark.asyncio
    async def test_enriches_market_with_depth(self):
        market = make_market(
            market_id="m1",
            clob_token_id_yes="tok-yes-123",
            book_depth_bids=None,
            book_depth_asks=None,
        )
        # Need clobTokenIds-like data; we'll mock the token lookup
        mock_response = MagicMock()
        mock_response.json.return_value = SAMPLE_BOOK
        mock_response.raise_for_status = MagicMock()

        with patch("scanner.pipeline.PolymarketClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.fetch_book.return_value = parse_clob_book(SAMPLE_BOOK)
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            config = ScannerConfig()
            enriched = await enrich_with_orderbook([market], config)

            assert len(enriched) == 1
            m = enriched[0]
            assert m.book_depth_bids is not None
            assert m.book_depth_asks is not None
            assert len(m.book_depth_bids) == 3
            assert m.total_bid_depth_usd > 0

    @pytest.mark.asyncio
    async def test_stale_book_clears_depth(self):
        """If book is stale (bid=0.01, ask=0.99), depth should be set to None."""
        market = make_market(market_id="m-stale", clob_token_id_yes="tok-stale", book_depth_bids=None, book_depth_asks=None)

        with patch("scanner.pipeline.PolymarketClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.fetch_book.return_value = parse_clob_book(STALE_BOOK)
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            config = ScannerConfig()
            enriched = await enrich_with_orderbook([market], config)

            m = enriched[0]
            # Stale book should result in None depth (flagged)
            assert m.book_depth_bids is None or len(m.book_depth_bids) == 0

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_market(self):
        """If book fetch fails, market should still be returned with None depth."""
        market = make_market(market_id="m-fail", clob_token_id_yes="tok-fail", book_depth_bids=None, book_depth_asks=None)

        with patch("scanner.pipeline.PolymarketClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.fetch_book.side_effect = Exception("API error")
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            config = ScannerConfig()
            enriched = await enrich_with_orderbook([market], config)

            assert len(enriched) == 1
            assert enriched[0].book_depth_bids is None

    @pytest.mark.asyncio
    async def test_fetches_all_markets(self):
        """Fetch books for all passed markets."""
        markets = [
            make_market(market_id=f"m{i}", clob_token_id_yes=f"tok-{i}", book_depth_bids=None, book_depth_asks=None)
            for i in range(10)
        ]

        fetch_count = 0

        async def mock_fetch_book(token_id):
            nonlocal fetch_count
            fetch_count += 1
            return parse_clob_book(SAMPLE_BOOK)

        with patch("scanner.pipeline.PolymarketClient") as MockClient:
            client_instance = AsyncMock()
            client_instance.fetch_book = mock_fetch_book
            client_instance.close = AsyncMock()
            MockClient.return_value = client_instance

            config = ScannerConfig()
            enriched = await enrich_with_orderbook(markets, config)

            assert fetch_count == 10  # all markets fetched
            assert enriched[0].book_depth_bids is not None
            assert enriched[9].book_depth_bids is not None


class TestOrderBookIntegrationWithScoring:
    def test_market_with_depth_scores_higher_liquidity(self):
        """Market with real depth data should score higher on liquidity than one without."""
        from scanner.config import FiltersConfig, ScoringWeights
        from scanner.scoring import compute_beauty_score

        m_with_depth = make_market(
            best_bid_yes=0.54, best_ask_yes=0.56,
            book_depth_bids=[BookLevel(price=0.54, size=2000), BookLevel(price=0.53, size=3000)],
            book_depth_asks=[BookLevel(price=0.56, size=2000), BookLevel(price=0.57, size=3000)],
        )
        m_no_depth = make_market(
            best_bid_yes=0.54, best_ask_yes=0.56,
            book_depth_bids=None, book_depth_asks=None,
        )

        s1 = compute_beauty_score(m_with_depth, ScoringWeights(), FiltersConfig())
        s2 = compute_beauty_score(m_no_depth, ScoringWeights(), FiltersConfig())

        assert s1.liquidity_depth > s2.liquidity_depth

    def test_depth_filter_rejects_shallow_book(self):
        """Market with very thin depth should be rejected by depth filter."""
        from scanner.config import FiltersConfig, HeuristicsConfig
        from scanner.filters import apply_hard_filters

        m = make_market(
            book_depth_bids=[BookLevel(price=0.54, size=30)],  # $30 total, below $100 min
            book_depth_asks=[BookLevel(price=0.56, size=30)],
        )
        result = apply_hard_filters(
            [m],
            FiltersConfig(min_bid_depth_usd=100),
            HeuristicsConfig(),
        )
        assert len(result.passed) == 0
        assert "depth" in result.rejected[0].reason.lower()
