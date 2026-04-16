"""Tests for _fetch_trades_batch — Data API trades fetching."""

import pytest
from unittest.mock import AsyncMock, MagicMock

import httpx

from scanner.daemon.poll_job import _fetch_trades_batch


def _make_market(market_id="m1", condition_id="0xabc"):
    m = MagicMock()
    m.market_id = market_id
    m.condition_id = condition_id
    return m


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    return resp


class TestFetchTradesBatch:
    @pytest.mark.asyncio
    async def test_list_response_format(self):
        """Data API returns trades as a plain list."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response([
            {"price": "0.55", "size": "100", "side": "BUY"},
            {"price": "0.54", "size": "50", "side": "SELL"},
        ])

        result = await _fetch_trades_batch(client, [_make_market()])

        assert "m1" in result
        assert len(result["m1"]) == 2
        assert result["m1"][0]["price"] == 0.55
        assert result["m1"][0]["size"] == 100.0
        assert result["m1"][0]["side"] == "BUY"

    @pytest.mark.asyncio
    async def test_dict_response_format(self):
        """Data API returns trades wrapped in {"data": [...]}."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response({
            "data": [
                {"price": "0.60", "size": "200", "side": "BUY"},
            ],
        })

        result = await _fetch_trades_batch(client, [_make_market()])

        assert "m1" in result
        assert len(result["m1"]) == 1
        assert result["m1"][0]["price"] == 0.60

    @pytest.mark.asyncio
    async def test_empty_condition_id_skipped(self):
        """Markets without condition_id should be silently skipped."""
        client = AsyncMock(spec=httpx.AsyncClient)

        m_no_cid = _make_market(market_id="m1", condition_id=None)
        m_with_cid = _make_market(market_id="m2", condition_id="0xdef")
        client.get.return_value = _mock_response([
            {"price": "0.50", "size": "10", "side": "BUY"},
        ])

        result = await _fetch_trades_batch(client, [m_no_cid, m_with_cid])

        assert "m1" not in result  # skipped
        assert "m2" in result

    @pytest.mark.asyncio
    async def test_http_error_silently_skipped(self):
        """Non-200 responses should be silently skipped."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response({}, status_code=429)

        result = await _fetch_trades_batch(client, [_make_market()])

        assert result == {}  # no trades stored

    @pytest.mark.asyncio
    async def test_exception_silently_skipped(self):
        """Network exceptions should be silently caught."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = httpx.ReadTimeout("timeout")

        result = await _fetch_trades_batch(client, [_make_market()])

        assert result == {}

    @pytest.mark.asyncio
    async def test_multiple_markets(self):
        """Should fetch trades for each market independently."""
        call_count = 0

        async def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return _mock_response([
                {"price": "0.50", "size": "10", "side": "BUY"},
            ])

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get = mock_get

        markets = [_make_market(f"m{i}", f"0x{i}") for i in range(5)]
        result = await _fetch_trades_batch(client, markets)

        assert call_count == 5
        assert len(result) == 5

    @pytest.mark.asyncio
    async def test_filters_entries_without_price(self):
        """Entries with price=None should be filtered out."""
        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.return_value = _mock_response([
            {"price": "0.55", "size": "100", "side": "BUY"},
            {"price": None, "size": "50", "side": "SELL"},  # filtered
            {"size": "30", "side": "BUY"},  # no price key, filtered
        ])

        result = await _fetch_trades_batch(client, [_make_market()])

        assert len(result["m1"]) == 1  # only the first one
