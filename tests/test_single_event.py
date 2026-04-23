"""Tests for single-event fetch + score flow."""

from unittest.mock import patch

import pytest

from polily.core.config import PolilyConfig
from polily.core.db import PolilyDB
from polily.scan.pipeline import fetch_and_score_event


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


SAMPLE_GAMMA_EVENT = {
    "id": "361227",
    "title": "Bitcoin above ___ on April 16?",
    "slug": "bitcoin-above-on-april-16",
    "description": "This market resolves based on the price of Bitcoin.",
    "markets": [
        {
            "id": "1928780",
            "conditionId": "0xabc",
            "questionID": "q1",
            "question": "Will BTC be above $74,000?",
            "groupItemTitle": "74,000",
            "outcomePrices": '["0.50", "0.50"]',
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["tok_yes", "tok_no"]',
            "volume": "500000",
            "active": True,
            "closed": False,
            "endDate": "2026-04-16T16:00:00Z",
            "acceptingOrders": True,
        },
    ],
    "negRisk": False,
    "volume": 500000,
    "startDate": "2026-04-10",
    "endDate": "2026-04-16T16:00:00Z",
    "active": True,
    "closed": False,
    "tags": '["crypto"]',
}


class TestFetchAndScoreEvent:
    @pytest.mark.asyncio
    async def test_returns_scored_result(self, db):
        """Should fetch event by slug, score it, persist to DB."""
        with patch("polily.scan.pipeline._fetch_event_by_slug") as mock_fetch, \
             patch("polily.scan.pipeline.enrich_with_orderbook") as mock_enrich, \
             patch("polily.scan.pipeline._fetch_price_params_batch") as mock_prices:
            mock_fetch.return_value = SAMPLE_GAMMA_EVENT
            mock_enrich.side_effect = lambda markets, config: markets
            mock_prices.return_value = {}

            result = await fetch_and_score_event("bitcoin-above-on-april-16", config=PolilyConfig(), db=db)

        assert result is not None
        assert result["event"].title == "Bitcoin above ___ on April 16?"
        assert len(result["markets"]) == 1
        assert 0 < result["event_score"].total <= 100

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self, db):
        with patch("polily.scan.pipeline._fetch_event_by_slug") as mock_fetch:
            mock_fetch.return_value = None
            result = await fetch_and_score_event("nonexistent-slug", config=PolilyConfig(), db=db)
        assert result is None

    @pytest.mark.asyncio
    async def test_persists_event_and_markets_to_db(self, db):
        with patch("polily.scan.pipeline._fetch_event_by_slug") as mock_fetch, \
             patch("polily.scan.pipeline.enrich_with_orderbook") as mock_enrich, \
             patch("polily.scan.pipeline._fetch_price_params_batch") as mock_prices:
            mock_fetch.return_value = SAMPLE_GAMMA_EVENT
            mock_enrich.side_effect = lambda markets, config: markets
            mock_prices.return_value = {}

            await fetch_and_score_event("bitcoin-above-on-april-16", config=PolilyConfig(), db=db)

        from polily.core.event_store import get_event, get_event_markets
        event = get_event("361227", db)
        assert event is not None
        markets = get_event_markets("361227", db)
        assert len(markets) >= 1
