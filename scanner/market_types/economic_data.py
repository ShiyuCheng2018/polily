"""Economic data market type plugin.

Handles markets like "Will CPI exceed 3.5% in March?"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.utils import count_matches

if TYPE_CHECKING:
    from scanner.models import Market


class EconomicDataPlugin:
    """Plugin for economic data / macro markets."""

    name = "economic_data"

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Classify based on keywords + economic indicator patterns."""
        keyword_score = min(1.0, count_matches(market.title, keywords) / 2.0) if keywords else 0.0

        title_lower = market.title.lower()
        strong_signals = ["cpi", "inflation", "rate cut", "fomc", "nonfarm", "gdp", "jobs report"]
        has_strong = any(s in title_lower for s in strong_signals)
        if has_strong:
            return max(keyword_score, 0.85)

        return keyword_score


plugin = EconomicDataPlugin()
