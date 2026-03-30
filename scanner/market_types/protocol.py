"""Market type module protocol definition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from scanner.models import Market


@runtime_checkable
class MarketTypeModule(Protocol):
    """Interface for market type modules.

    Required:
        name: str — must match config.yaml market_types key
        classify(market, keywords) -> float — 0.0-1.0 confidence

    Optional:
        fetch_price_params(market, config) -> dict | None — async, fetch external data
        detect_mispricing(market, price_params, config) -> MispricingResult | None — sync
    """

    name: str

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Return 0.0-1.0 confidence that this market belongs to this type."""
        ...
