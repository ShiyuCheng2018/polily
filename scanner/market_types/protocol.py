"""Data enrichment module protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from scanner.config import ScannerConfig
    from scanner.mispricing import MispricingResult
    from scanner.models import Market


@runtime_checkable
class DataEnrichmentModule(Protocol):
    """Interface for data enrichment modules.

    Classification is done by tag_classifier using Polymarket tags.
    Modules handle external data fetching and custom mispricing detection.

    Required:
        name: str — identifier for this module
        matches(market) -> bool — whether this module should process a market
        fetch_price_params(market, config) -> dict | None — async, fetch external data
        detect_mispricing(market, price_params, config) -> MispricingResult | None — sync
    """

    name: str

    def matches(self, market: Market) -> bool:
        """Whether this module should enrich this market."""
        ...

    async def fetch_price_params(self, market: Market, config: ScannerConfig) -> dict | None:
        """Fetch external price data for mispricing detection."""
        ...

    def detect_mispricing(self, market: Market, price_params: dict, config: ScannerConfig) -> MispricingResult | None:
        """Custom mispricing detection using fetched data."""
        ...
