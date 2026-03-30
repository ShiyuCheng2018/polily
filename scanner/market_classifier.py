"""Market type classifier: plugin-first with keyword fallback."""

from scanner.config import MarketTypeConfig
from scanner.models import Market
from scanner.utils import count_matches


def classify_market_type(
    market: Market,
    type_configs: dict[str, MarketTypeConfig],
) -> str:
    """Classify a market into a type.

    Priority: plugin.classify() > keyword count fallback.
    Returns the type with the highest confidence, or "other" if none match.
    """
    from scanner.market_types.registry import discover_plugins

    plugins = discover_plugins()
    best_type = "other"
    best_score = 0.0

    for type_name, config in type_configs.items():
        plugin = plugins.get(type_name)
        if plugin is not None:
            score = min(1.0, plugin.classify(market, config.keywords))
        else:
            # Fallback: keyword counting, normalized to 0-1
            hits = count_matches(market.title, config.keywords)
            score = min(1.0, hits / 3.0) if config.keywords else 0.0

        if score > best_score:
            best_score = score
            best_type = type_name

    return best_type
