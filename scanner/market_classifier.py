"""Market type classifier: module-first with keyword fallback."""

from scanner.config import MarketTypeConfig
from scanner.models import Market
from scanner.utils import count_matches

MIN_CONFIDENCE = 0.3  # Below this, classify as "other"


def classify_market_type(
    market: Market,
    type_configs: dict[str, MarketTypeConfig],
) -> str:
    """Classify a market into a type.

    Priority: module.classify() > keyword count fallback.
    Returns the type with the highest confidence (>= MIN_CONFIDENCE), or "other".
    """
    from scanner.market_types.registry import discover_modules

    modules = discover_modules()
    best_type = "other"
    best_score = 0.0

    for type_name, config in type_configs.items():
        module = modules.get(type_name)
        if module is not None:
            score = min(1.0, module.classify(market, config.keywords))
        else:
            hits = count_matches(market.title, config.keywords)
            score = min(1.0, hits / 3.0) if config.keywords else 0.0

        if score > best_score:
            best_score = score
            best_type = type_name

    return best_type if best_score >= MIN_CONFIDENCE else "other"
