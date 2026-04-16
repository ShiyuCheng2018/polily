"""Opinion matching: find markets that match a user's directional view."""

import re
from dataclasses import dataclass

from scanner.core.models import Market


@dataclass
class MatchResult:
    market: Market
    relevance_score: int  # keyword overlap count
    cost: float  # yes_price per share
    payoff_if_right: float  # (1.0 - yes_price) per share on $20
    suggested_side: str  # "yes" or "no"


def find_matching_markets(
    view: str,
    markets: list[Market],
    max_results: int = 5,
) -> list[MatchResult]:
    """Find markets matching a user's natural language view.

    Uses keyword overlap scoring. For AI-enhanced matching,
    wrap this with an agent call.
    """
    view_tokens = _tokenize(view)
    if not view_tokens:
        return []

    results = []
    for market in markets:
        title_tokens = _tokenize(market.title)
        overlap = len(view_tokens & title_tokens)
        if overlap == 0:
            continue

        yes_price = market.yes_price or 0.5
        # Determine suggested side from view sentiment
        # If view contains bullish keywords matching "above"/"will"/"hit" → buy YES
        # If view contains "below"/"drop"/"fall"/"crash" → buy NO
        side = _infer_side(view)

        if side == "yes":
            cost = yes_price
            payoff = (1.0 / yes_price - 1.0) * 20.0 if yes_price > 0 else 0
        else:
            no_price = 1.0 - yes_price
            cost = no_price
            payoff = (1.0 / no_price - 1.0) * 20.0 if no_price > 0 else 0

        results.append(MatchResult(
            market=market,
            relevance_score=overlap,
            cost=cost,
            payoff_if_right=payoff,
            suggested_side=side,
        ))

    results.sort(key=lambda r: r.relevance_score, reverse=True)
    return results[:max_results]


def _tokenize(text: str) -> set[str]:
    """Extract meaningful tokens from text."""
    text_lower = text.lower()
    # Remove common words and punctuation
    text_clean = re.sub(r'[^\w\s]', ' ', text_lower)
    stop_words = {"will", "be", "the", "a", "an", "on", "in", "by", "to", "of", "is", "it", "that", "this"}
    tokens = set(text_clean.split()) - stop_words
    # Remove very short tokens
    return {t for t in tokens if len(t) >= 2}


def _infer_side(view: str) -> str:
    """Infer whether the view is bullish (YES) or bearish (NO)."""
    view_tokens = set(re.sub(r'[^\w\s]', ' ', view.lower()).split())
    bearish = {"below", "drop", "fall", "crash", "decline", "down", "decrease",
               "fail", "not", "never", "lose", "miss", "reject", "lower", "bearish", "short"}
    if view_tokens & bearish:
        return "no"
    return "yes"
