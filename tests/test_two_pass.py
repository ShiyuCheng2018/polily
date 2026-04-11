"""Tests for two-pass scan: metadata fetch → filter → order book fetch → score."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.core.config import ScannerConfig
from scanner.core.models import BookLevel
from scanner.scan.pipeline import enrich_with_orderbook
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


def _mock_httpx_response(book_data, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = book_data
    resp.raise_for_status = MagicMock()
    if status >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class TestEnrichWithOrderbook:
    @pytest.mark.asyncio
    async def test_enriches_market_with_depth(self):
        market = make_market(
            market_id="m1",
            clob_token_id_yes="tok-yes-123",
            book_depth_bids=None,
            book_depth_asks=None,
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_httpx_response(SAMPLE_BOOK))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scanner.scan.pipeline.httpx.AsyncClient", return_value=mock_client):
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
        market = make_market(market_id="m-stale", clob_token_id_yes="tok-stale",
                            book_depth_bids=None, book_depth_asks=None)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_httpx_response(STALE_BOOK))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scanner.scan.pipeline.httpx.AsyncClient", return_value=mock_client):
            config = ScannerConfig()
            enriched = await enrich_with_orderbook([market], config)

            m = enriched[0]
            assert m.book_depth_bids is None or len(m.book_depth_bids) == 0

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_market(self):
        market = make_market(market_id="m-fail", clob_token_id_yes="tok-fail",
                            book_depth_bids=None, book_depth_asks=None)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("API error"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scanner.scan.pipeline.httpx.AsyncClient", return_value=mock_client):
            config = ScannerConfig()
            enriched = await enrich_with_orderbook([market], config)

            assert len(enriched) == 1
            assert enriched[0].book_depth_bids is None

    @pytest.mark.asyncio
    async def test_fetches_all_markets_concurrently(self):
        markets = [
            make_market(market_id=f"m{i}", clob_token_id_yes=f"tok-{i}",
                       book_depth_bids=None, book_depth_asks=None)
            for i in range(10)
        ]

        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_httpx_response(SAMPLE_BOOK)

        mock_client = AsyncMock()
        mock_client.get = mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("scanner.scan.pipeline.httpx.AsyncClient", return_value=mock_client):
            config = ScannerConfig()
            enriched = await enrich_with_orderbook(markets, config)

            assert call_count == 10
            assert enriched[0].book_depth_bids is not None
            assert enriched[9].book_depth_bids is not None


class TestOrderBookIntegrationWithScoring:
    def test_market_with_depth_scores_higher_liquidity(self):
        from scanner.scan.scoring import compute_structure_score

        m_with_depth = make_market(
            best_bid_yes=0.54, best_ask_yes=0.56,
            book_depth_bids=[BookLevel(price=0.54, size=2000), BookLevel(price=0.53, size=3000)],
            book_depth_asks=[BookLevel(price=0.56, size=2000), BookLevel(price=0.57, size=3000)],
        )
        m_no_depth = make_market(
            best_bid_yes=0.54, best_ask_yes=0.56,
            book_depth_bids=None, book_depth_asks=None,
        )

        s1 = compute_structure_score(m_with_depth)
        s2 = compute_structure_score(m_no_depth)

        assert s1.liquidity_structure > s2.liquidity_structure

    def test_depth_filter_rejects_shallow_book(self):
        from scanner.core.config import FiltersConfig, HeuristicsConfig
        from scanner.scan.filters import apply_hard_filters

        m = make_market(
            book_depth_bids=[BookLevel(price=0.54, size=30)],
            book_depth_asks=[BookLevel(price=0.56, size=30)],
        )
        result = apply_hard_filters(
            [m],
            FiltersConfig(min_bid_depth_usd=100),
            HeuristicsConfig(),
        )
        assert len(result.passed) == 0
        assert "depth" in result.rejected[0].reason.lower()
