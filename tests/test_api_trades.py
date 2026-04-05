import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from scanner.api import PolymarketClient, parse_data_api_trades
from scanner.config import ApiConfig


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
