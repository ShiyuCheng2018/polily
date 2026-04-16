from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.api import PolymarketClient, parse_data_api_trades, parse_gamma_event
from scanner.core.config import ApiConfig


def test_parse_data_api_trades():
    raw = [
        {"transactionHash": "0xabc", "price": 0.6, "size": 200, "side": "SELL", "timestamp": 1775397473},
        {"transactionHash": "0xdef", "price": 0.615, "size": 5.36, "side": "BUY", "timestamp": 1775397487},
    ]
    trades = parse_data_api_trades(raw)
    assert len(trades) == 2
    assert trades[0].price == 0.6
    assert trades[0].size == 200
    assert trades[0].side == "SELL"
    assert trades[1].size == 5.36


@pytest.mark.asyncio
async def test_fetch_trades_empty_condition_id():
    """fetch_trades returns empty list with no condition_id."""
    config = ApiConfig()
    client = PolymarketClient(config)
    trades = await client.fetch_trades("")
    assert trades == []
    await client.close()


@pytest.mark.asyncio
async def test_fetch_trades_calls_data_api():
    config = ApiConfig()
    client = PolymarketClient(config)

    mock_response = MagicMock()
    mock_response.json.return_value = [
        {"transactionHash": "0xabc", "price": 0.6, "size": 100, "side": "BUY", "timestamp": 1775397473},
    ]

    with patch.object(client, "_get", new_callable=AsyncMock, return_value=mock_response):
        trades = await client.fetch_trades("0x1234conditionid")
        assert len(trades) == 1
        assert trades[0].price == 0.6
    await client.close()


def test_parse_gamma_event_includes_condition_id():
    """condition_id should be parsed from Gamma API response."""
    event_data = {
        "id": "event_1",
        "slug": "test-event",
        "openInterest": 50000,
        "tags": [],
        "markets": [
            {
                "id": "market_abc",
                "question": "Will BTC be above $100K?",
                "outcomes": '["Yes","No"]',
                "outcomePrices": '[0.55,0.45]',
                "clobTokenIds": '["tok_yes","tok_no"]',
                "conditionId": "0xabc123condition",
            }
        ],
    }
    _event_row, markets = parse_gamma_event(event_data)
    assert len(markets) == 1
    assert markets[0].condition_id == "0xabc123condition"
    assert markets[0].clob_token_id_yes == "tok_yes"
    assert markets[0].clob_token_id_no == "tok_no"
