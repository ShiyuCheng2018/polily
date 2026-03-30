"""Market type classifier based on keyword matching."""

from scanner.config import MarketTypeConfig
from scanner.models import Market
from scanner.utils import count_matches


def classify_market_type(
    market: Market,
    type_configs: dict[str, MarketTypeConfig],
) -> str:
    """Classify a market into a type based on title keyword matching.

    Returns the type with the most keyword hits, or "other" if none match.
    """
    best_type = "other"
    best_hits = 0

    for type_name, config in type_configs.items():
        hits = count_matches(market.title, config.keywords)
        if hits > best_hits:
            best_hits = hits
            best_type = type_name

    return best_type
