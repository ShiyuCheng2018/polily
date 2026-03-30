"""Crypto threshold market type plugin.

Handles markets like "Will Bitcoin be above $100,000 by June 30?"
Uses log-normal volatility model via Binance price feed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.price_feeds import BinancePriceFeed, extract_crypto_asset, extract_threshold_price
from scanner.utils import count_matches

if TYPE_CHECKING:
    from scanner.config import ScannerConfig
    from scanner.mispricing import MispricingResult
    from scanner.models import Market


class CryptoThresholdPlugin:
    """Plugin for crypto price threshold markets."""

    name = "crypto_threshold"

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Classify based on keywords + crypto asset + price threshold in title."""
        keyword_score = min(1.0, count_matches(market.title, keywords) / 3.0) if keywords else 0.0

        has_asset = extract_crypto_asset(market.title) is not None
        has_threshold = extract_threshold_price(market.title) is not None

        if has_asset and has_threshold:
            return max(keyword_score, 0.9)
        if has_asset:
            return max(keyword_score, 0.5)
        return keyword_score

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


plugin = CryptoThresholdPlugin()
