"""Price feeds: fetch crypto prices and volatility via ccxt (Binance)."""

import logging
import math
import os
import re

logger = logging.getLogger(__name__)

# Map common crypto tickers/names to ccxt trading pair format
CRYPTO_PAIRS = {
    "btc": "BTC/USDT", "bitcoin": "BTC/USDT",
    "eth": "ETH/USDT", "ethereum": "ETH/USDT",
    "sol": "SOL/USDT", "solana": "SOL/USDT",
    "matic": "MATIC/USDT", "polygon": "MATIC/USDT",
    "doge": "DOGE/USDT", "dogecoin": "DOGE/USDT",
    "avax": "AVAX/USDT", "avalanche": "AVAX/USDT",
    "bnb": "BNB/USDT",
    "xrp": "XRP/USDT",
    "ada": "ADA/USDT",
    "dot": "DOT/USDT",
    "link": "LINK/USDT",
}


def extract_crypto_asset(title: str) -> str | None:
    """Extract ccxt trading pair from market title."""
    title_lower = title.lower()
    for alias, pair in CRYPTO_PAIRS.items():
        if alias in title_lower.split() or alias in title_lower:
            return pair
    return None


def extract_threshold_price(title: str) -> float | None:
    """Extract threshold price from title like '$88,000' or '88000'."""
    match = re.search(r'\$?([\d,]+(?:\.\d+)?)', title)
    if not match:
        return None
    try:
        val = float(match.group(1).replace(",", ""))
        if val < 100:
            return None
        return val
    except ValueError:
        return None


def compute_realized_vol(prices: list[float], annualize_factor: float = 365.0) -> float:
    """Compute annualized realized volatility from daily prices."""
    if len(prices) < 2:
        return 0.0
    log_returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] > 0 and prices[i] > 0:
            log_returns.append(math.log(prices[i] / prices[i - 1]))
    if not log_returns:
        return 0.0
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / len(log_returns)
    daily_vol = math.sqrt(variance)
    return daily_vol * math.sqrt(annualize_factor)


class BinancePriceFeed:
    """Fetch crypto prices via ccxt (Binance). No API key needed for market data."""

    def __init__(self):
        self._exchange = None

    async def _get_exchange(self):
        if self._exchange is None:
            import ccxt.async_support as ccxt
            config = {"enableRateLimit": True}
            # Support proxy via HTTPS_PROXY or POLILY_PROXY env var
            proxy = os.environ.get("POLILY_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
            if proxy:
                config["proxies"] = {"http": proxy, "https": proxy}
            self._exchange = ccxt.binance(config)
        return self._exchange

    async def get_current_price(self, symbol: str) -> float | None:
        """Fetch current price for a trading pair like 'BTC/USDT'."""
        try:
            exchange = await self._get_exchange()
            ticker = await exchange.fetch_ticker(symbol)
            return ticker.get("last")
        except Exception as e:
            logger.warning("Failed to fetch price for %s: %s", symbol, e)
            return None

    async def get_historical_prices(self, symbol: str, days: int = 30) -> list[float]:
        """Fetch daily close prices for vol calculation."""
        try:
            exchange = await self._get_exchange()
            ohlcv = await exchange.fetch_ohlcv(symbol, "1d", limit=days)
            return [candle[4] for candle in ohlcv]  # index 4 = close
        except Exception as e:
            logger.warning("Failed to fetch OHLCV for %s: %s", symbol, e)
            return []

    async def get_short_term_prices(self, symbol: str, timeframe: str = "1h",
                                     limit: int = 24) -> list[float]:
        """Fetch short-term close prices (e.g., hourly) for signal calculation."""
        try:
            exchange = await self._get_exchange()
            ohlcv = await exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return [candle[4] for candle in ohlcv]  # index 4 = close
        except Exception as e:
            logger.warning("Failed to fetch %s OHLCV for %s: %s", timeframe, symbol, e)
            return []

    async def get_crypto_params(self, market_title: str, vol_days: int = 30) -> dict | None:
        """Extract asset from title, fetch price + vol, return mispricing params."""
        symbol = extract_crypto_asset(market_title)
        if not symbol:
            return None

        threshold = extract_threshold_price(market_title)
        if not threshold:
            return None

        price = await self.get_current_price(symbol)
        if price is None:
            return None

        history = await self.get_historical_prices(symbol, days=vol_days)
        vol = compute_realized_vol(history) if history else 0.60  # BTC rough annual vol fallback

        vol_source = f"{len(history)}d_binance" if history else "fallback_default"

        return {
            "current_underlying_price": price,
            "threshold_price": threshold,
            "annual_volatility": vol,
            "vol_source": vol_source,
            "vol_data_days": len(history),
        }

    async def close(self):
        if self._exchange:
            await self._exchange.close()
            self._exchange = None
