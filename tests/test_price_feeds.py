"""Tests for price feed (Binance via ccxt) integration."""

from unittest.mock import AsyncMock

import pytest

from scanner.price_feeds import (
    BinancePriceFeed,
    compute_realized_vol,
    extract_crypto_asset,
    extract_threshold_price,
)


class TestExtractCryptoAsset:
    def test_btc_title(self):
        assert extract_crypto_asset("Will BTC be above $88,000 on March 30?") == "BTC/USDT"

    def test_bitcoin_title(self):
        assert extract_crypto_asset("Bitcoin above 100K?") == "BTC/USDT"

    def test_eth_title(self):
        assert extract_crypto_asset("Will ETH be above $2,100?") == "ETH/USDT"

    def test_sol_title(self):
        assert extract_crypto_asset("SOL above $200?") == "SOL/USDT"

    def test_unknown_returns_none(self):
        assert extract_crypto_asset("Will Trump win?") is None


class TestExtractThresholdPrice:
    def test_with_dollar_sign(self):
        assert extract_threshold_price("BTC above $88,000?") == 88000.0

    def test_without_dollar(self):
        assert extract_threshold_price("BTC above 100000") == 100000.0

    def test_with_comma(self):
        assert extract_threshold_price("ETH above $2,100 on April 1") == 2100.0

    def test_no_match(self):
        assert extract_threshold_price("Will Trump win?") is None

    def test_percentage_excluded(self):
        assert extract_threshold_price("CPI above 3.5%?") is None


class TestComputeRealizedVol:
    def test_stable_prices(self):
        assert compute_realized_vol([100.0] * 30) == 0.0

    def test_volatile_prices(self):
        prices = [100, 105, 100, 105, 100, 105] * 5
        assert compute_realized_vol(prices) > 0.1

    def test_empty(self):
        assert compute_realized_vol([]) == 0.0

    def test_single(self):
        assert compute_realized_vol([100.0]) == 0.0


class TestBinancePriceFeed:
    @pytest.mark.asyncio
    async def test_get_current_price(self):
        feed = BinancePriceFeed()
        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.return_value = {"last": 87500.0}
        feed._exchange = mock_exchange

        price = await feed.get_current_price("BTC/USDT")
        assert price == 87500.0
        mock_exchange.fetch_ticker.assert_called_with("BTC/USDT")

    @pytest.mark.asyncio
    async def test_get_current_price_failure(self):
        feed = BinancePriceFeed()
        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.side_effect = Exception("Network error")
        feed._exchange = mock_exchange

        price = await feed.get_current_price("BTC/USDT")
        assert price is None

    @pytest.mark.asyncio
    async def test_get_historical_prices(self):
        feed = BinancePriceFeed()
        mock_exchange = AsyncMock()
        # ccxt ohlcv format: [timestamp, open, high, low, close, volume]
        mock_exchange.fetch_ohlcv.return_value = [
            [1700000000000, 85000, 86000, 84000, 85500, 1000],
            [1700086400000, 85500, 87000, 85000, 86500, 1200],
            [1700172800000, 86500, 88000, 86000, 87500, 1100],
        ]
        feed._exchange = mock_exchange

        prices = await feed.get_historical_prices("BTC/USDT", days=30)
        assert prices == [85500, 86500, 87500]  # close prices (index 4)

    @pytest.mark.asyncio
    async def test_get_crypto_params(self):
        feed = BinancePriceFeed()
        mock_exchange = AsyncMock()
        mock_exchange.fetch_ticker.return_value = {"last": 87500.0}
        mock_exchange.fetch_ohlcv.return_value = [
            [i * 86400000, 85000, 86000, 84000, 85000 + i * 100, 1000]
            for i in range(30)
        ]
        feed._exchange = mock_exchange

        params = await feed.get_crypto_params("Will BTC be above $88,000 on March 30?")

        assert params is not None
        assert params["current_underlying_price"] == 87500.0
        assert params["threshold_price"] == 88000.0
        assert params["annual_volatility"] > 0

    @pytest.mark.asyncio
    async def test_get_crypto_params_non_crypto(self):
        feed = BinancePriceFeed()
        params = await feed.get_crypto_params("Will Trump win the election?")
        assert params is None
