"""Tests for paper trade auto-resolve via Polymarket API."""

import tempfile
from unittest.mock import AsyncMock, patch

import pytest

from scanner.auto_resolve import auto_resolve_trades
from scanner.paper_trading import PaperTradingDB


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = PaperTradingDB(db_path)
    yield store
    store.close()


class TestAutoResolve:
    @pytest.mark.asyncio
    async def test_resolves_closed_market(self, db):
        t = db.mark(market_id="m-resolved", title="Test", side="yes", entry_price=0.50)

        mock_market = {
            "id": "m-resolved",
            "closed": True,
            "resolved": True,
            "outcomePrices": '["1.00", "0.00"]',  # YES won
        }

        with patch("scanner.auto_resolve.fetch_market_status", new_callable=AsyncMock, return_value=mock_market):
            resolved_count = await auto_resolve_trades(db)

        assert resolved_count == 1
        trade = db.get(t.id)
        assert trade.status == "resolved"
        assert trade.resolved_result == "yes"

    @pytest.mark.asyncio
    async def test_skips_unresolved_market(self, db):
        db.mark(market_id="m-open", title="Test", side="yes", entry_price=0.50)

        mock_market = {"id": "m-open", "closed": False, "resolved": False}

        with patch("scanner.auto_resolve.fetch_market_status", new_callable=AsyncMock, return_value=mock_market):
            resolved_count = await auto_resolve_trades(db)

        assert resolved_count == 0

    @pytest.mark.asyncio
    async def test_handles_api_failure(self, db):
        db.mark(market_id="m-fail", title="Test", side="yes", entry_price=0.50)

        with patch("scanner.auto_resolve.fetch_market_status", new_callable=AsyncMock, side_effect=Exception("API error")):
            resolved_count = await auto_resolve_trades(db)

        assert resolved_count == 0
        # Trade still open
        assert len(db.list_open()) == 1

    @pytest.mark.asyncio
    async def test_no_open_trades(self, db):
        resolved_count = await auto_resolve_trades(db)
        assert resolved_count == 0
