"""Political market type plugin.

Handles markets like "Will the next President be a Democrat?"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.utils import count_matches

if TYPE_CHECKING:
    from scanner.models import Market


class PoliticalPlugin:
    """Plugin for political prediction markets."""

    name = "political"

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Classify based on keywords + political entity patterns."""
        keyword_score = min(1.0, count_matches(market.title, keywords) / 2.0) if keywords else 0.0

        title_lower = market.title.lower()
        # Boost for strong political indicators
        strong_signals = ["election", "president", "senate", "governor", "prime minister", "parliament"]
        has_strong = any(s in title_lower for s in strong_signals)
        if has_strong:
            return max(keyword_score, 0.85)

        return keyword_score


plugin = PoliticalPlugin()
