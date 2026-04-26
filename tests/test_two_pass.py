"""Tests for two-pass scan: metadata fetch → filter → order book fetch → score."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from polily.core.config import PolilyConfig
from polily.core.models import BookLevel
from polily.scan.pipeline import enrich_with_orderbook
from tests.conftest import make_market


def _clob_result(**overrides):
    """Build a realistic fetch_clob_market_data return dict."""
    base = {
        "yes_price": 0.55,
        "no_price": 0.45,
        "last_trade_price": 0.55,
        "best_bid": 0.54,
        "best_ask": 0.56,
        "spread": 0.02,
        "bid_depth": 4600.0,
        "ask_depth": 3700.0,
        "book_bids": json.dumps([
            {"price": 0.54, "size": 1500},
            {"price": 0.53, "size": 2200},
            {"price": 0.52, "size": 900},
        ]),
        "book_asks": json.dumps([
            {"price": 0.56, "size": 1300},
            {"price": 0.57, "size": 1800},
            {"price": 0.58, "size": 600},
        ]),
    }
    base.update(overrides)
    return base


class TestEnrichWithOrderbook:
    @pytest.mark.asyncio
    async def test_enriches_market_with_depth(self):
        market = make_market(
            market_id="m1",
            clob_token_id_yes="tok-yes-123",
            book_depth_bids=None,
            book_depth_asks=None,
        )

        with patch("polily.core.clob.fetch_clob_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _clob_result()
            config = PolilyConfig()
            enriched = await enrich_with_orderbook([market], config)

            assert len(enriched) == 1
            m = enriched[0]
            assert m.book_depth_bids is not None
            assert m.book_depth_asks is not None
            assert len(m.book_depth_bids) == 3
            assert m.total_bid_depth_usd > 0

    @pytest.mark.asyncio
    async def test_sets_real_bid_ask_from_price_endpoint(self):
        """enrich should set best_bid_yes/best_ask_yes from /price data."""
        market = make_market(
            market_id="m1",
            clob_token_id_yes="tok-yes-123",
            best_bid_yes=None,
            best_ask_yes=None,
        )

        with patch("polily.core.clob.fetch_clob_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _clob_result(best_bid=0.54, best_ask=0.56, spread=0.02)
            config = PolilyConfig()
            enriched = await enrich_with_orderbook([market], config)

            m = enriched[0]
            assert m.best_bid_yes == 0.54
            assert m.best_ask_yes == 0.56
            assert m.spread_yes == 0.02

    @pytest.mark.asyncio
    async def test_neg_risk_book_depth_still_stored(self):
        """negRisk markets with bid=0.01 in /book should still store depth (not cleared)."""
        market = make_market(market_id="m-neg", clob_token_id_yes="tok-neg",
                            book_depth_bids=None, book_depth_asks=None)

        with patch("polily.core.clob.fetch_clob_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _clob_result(
                best_bid=0.54,    # from /price (correct)
                best_ask=0.56,    # from /price (correct)
                spread=0.02,
                book_bids=json.dumps([{"price": 0.01, "size": 100}]),  # /book raw (negRisk)
                book_asks=json.dumps([{"price": 0.99, "size": 100}]),
            )
            config = PolilyConfig()
            enriched = await enrich_with_orderbook([market], config)

            m = enriched[0]
            # Depth is stored (not cleared — no more stale book detection)
            assert m.book_depth_bids is not None
            assert len(m.book_depth_bids) == 1
            # But bid/ask come from /price, not /book
            assert m.best_bid_yes == 0.54
            assert m.best_ask_yes == 0.56

    @pytest.mark.asyncio
    async def test_fetch_failure_keeps_market(self):
        market = make_market(market_id="m-fail", clob_token_id_yes="tok-fail",
                            book_depth_bids=None, book_depth_asks=None)

        with patch("polily.core.clob.fetch_clob_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("API error")
            config = PolilyConfig()
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

        with patch("polily.core.clob.fetch_clob_market_data", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = _clob_result()
            config = PolilyConfig()
            enriched = await enrich_with_orderbook(markets, config)

            assert mock_fetch.call_count == 10
            assert enriched[0].book_depth_bids is not None
            assert enriched[9].book_depth_bids is not None


class TestOrderBookIntegrationWithScoring:
    def test_market_with_depth_scores_higher_liquidity(self):
        from polily.scan.scoring import compute_structure_score

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
