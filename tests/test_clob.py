"""Tests for scanner.core.clob — shared CLOB data fetching."""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock

from scanner.core.clob import fetch_clob_market_data


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp,
        )
    return resp


def _route_factory(book_resp, mid_resp, price_buy_resp, price_sell_resp):
    """Build a route_get function for mocking client.get."""
    async def route_get(url, **kwargs):
        if "/book" in url:
            return book_resp
        if "/midpoint" in url:
            return mid_resp
        if "/price" in url:
            params = kwargs.get("params", {})
            if params.get("side") == "BUY":
                return price_buy_resp
            return price_sell_resp
        raise ValueError(f"Unexpected URL: {url}")
    return route_get


@pytest.mark.asyncio
async def test_all_endpoints_success():
    """All 4 endpoints return valid data — verify correct field mapping."""
    book_resp = _mock_response({
        "bids": [
            {"price": "0.01", "size": "5000"},
            {"price": "0.005", "size": "3000"},
        ],
        "asks": [
            {"price": "0.99", "size": "4000"},
            {"price": "0.995", "size": "2000"},
        ],
    })
    mid_resp = _mock_response({"mid": "0.55"})
    # BUY side = bid (what buyers offer), SELL side = ask (what sellers want)
    price_buy_resp = _mock_response({"price": "0.54"})
    price_sell_resp = _mock_response({"price": "0.56"})

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=_route_factory(
        book_resp, mid_resp, price_buy_resp, price_sell_resp,
    ))

    result = await fetch_clob_market_data(client, "tok_abc")

    assert result["yes_price"] == 0.55
    assert result["no_price"] == 0.45
    assert result["best_bid"] == 0.54   # /price BUY = bid
    assert result["best_ask"] == 0.56   # /price SELL = ask
    assert result["spread"] == pytest.approx(0.02)
    assert result["bid_depth"] == 8000.0
    assert result["ask_depth"] == 6000.0
    assert result["book_bids"] is not None
    assert result["book_asks"] is not None
    assert result["last_trade_price"] == 0.55


@pytest.mark.asyncio
async def test_price_endpoint_failure_returns_none():
    """/price fails — bid/ask/spread = None, other fields normal."""
    book_resp = _mock_response({
        "bids": [{"price": "0.54", "size": "5000"}],
        "asks": [{"price": "0.56", "size": "4000"}],
    })
    mid_resp = _mock_response({"mid": "0.55"})

    client = AsyncMock(spec=httpx.AsyncClient)

    async def route_get(url, **kwargs):
        if "/book" in url:
            return book_resp
        if "/midpoint" in url:
            return mid_resp
        if "/price" in url:
            raise httpx.ReadTimeout("timeout")
        raise ValueError(f"Unexpected URL: {url}")

    client.get = AsyncMock(side_effect=route_get)

    result = await fetch_clob_market_data(client, "tok_abc")

    assert result["yes_price"] == 0.55
    assert result["best_bid"] is None
    assert result["best_ask"] is None
    assert result["spread"] is None
    # book depth still available
    assert result["bid_depth"] == 5000.0
    assert result["ask_depth"] == 4000.0


@pytest.mark.asyncio
async def test_midpoint_failure_returns_none():
    """/midpoint fails — yes_price = None, bid/ask still available."""
    book_resp = _mock_response({
        "bids": [{"price": "0.54", "size": "5000"}],
        "asks": [{"price": "0.56", "size": "4000"}],
    })
    # BUY side = bid = 0.54, SELL side = ask = 0.56
    price_buy_resp = _mock_response({"price": "0.54"})
    price_sell_resp = _mock_response({"price": "0.56"})

    client = AsyncMock(spec=httpx.AsyncClient)

    async def route_get(url, **kwargs):
        if "/book" in url:
            return book_resp
        if "/midpoint" in url:
            raise httpx.ReadTimeout("timeout")
        if "/price" in url:
            params = kwargs.get("params", {})
            if params.get("side") == "BUY":
                return price_buy_resp
            return price_sell_resp
        raise ValueError(f"Unexpected URL: {url}")

    client.get = AsyncMock(side_effect=route_get)

    result = await fetch_clob_market_data(client, "tok_abc")

    assert result["yes_price"] is None
    assert result["no_price"] is None
    assert result["last_trade_price"] is None
    assert result["best_bid"] == 0.54
    assert result["best_ask"] == 0.56
    assert result["spread"] == pytest.approx(0.02)


@pytest.mark.asyncio
async def test_book_failure_raises():
    """/book fails — should raise HTTPStatusError (404 = market closed)."""
    client = AsyncMock(spec=httpx.AsyncClient)

    async def route_get(url, **kwargs):
        if "/book" in url:
            return _mock_response({}, status_code=404)
        # Other endpoints should not be called
        raise ValueError(f"Unexpected URL: {url}")

    client.get = AsyncMock(side_effect=route_get)

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_clob_market_data(client, "tok_abc")
