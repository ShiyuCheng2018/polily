"""Crypto threshold data enrichment module.

Enriches markets like "Will Bitcoin be above $100,000 by June 30?"
with Binance price data and log-normal mispricing detection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.price_feeds import BinancePriceFeed, extract_crypto_asset, extract_threshold_price

if TYPE_CHECKING:
    from scanner.config import ScannerConfig
    from scanner.mispricing import MispricingResult
    from scanner.models import Market


class CryptoThreshold:
    """Data enrichment for crypto price threshold markets."""

    name = "crypto_threshold"

    def matches(self, market: Market) -> bool:
        """Match crypto markets with a price threshold in the title."""
        has_asset = extract_crypto_asset(market.title) is not None
        has_threshold = extract_threshold_price(market.title) is not None
        return has_asset and has_threshold

    async def fetch_price_params(self, market: Market, config: ScannerConfig) -> dict | None:
        """Fetch Binance price + realized volatility."""
        feed = BinancePriceFeed()
        try:
            return await feed.get_crypto_params(
                market.title,
                vol_days=config.mispricing.crypto.volatility_lookback_days,
            )
        except Exception:
            return None
        finally:
            await feed.close()

    def detect_mispricing(
        self, market: Market, price_params: dict, config: ScannerConfig,
    ) -> MispricingResult | None:
        """Detect mispricing using log-normal vol model."""
        from scanner.mispricing import detect_mispricing
        return detect_mispricing(market, config.mispricing, **price_params)


module = CryptoThreshold()
