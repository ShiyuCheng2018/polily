"""Sports market type plugin.

Handles markets like "Lakers vs. Celtics" or "Who wins the Super Bowl?"
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from scanner.utils import count_matches

if TYPE_CHECKING:
    from scanner.models import Market


class SportsPlugin:
    """Plugin for sports prediction markets."""

    name = "sports"

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Classify based on keywords + team matchup patterns."""
        keyword_score = min(1.0, count_matches(market.title, keywords) / 2.0) if keywords else 0.0

        # "Team A vs. Team B" pattern — but exclude known non-sports contexts
        title_lower = market.title.lower()
        has_vs = bool(re.search(r"\bvs\.?\b", market.title, re.IGNORECASE))
        non_sports_vs = any(w in title_lower for w in [
            "bitcoin", "btc", "ethereum", "crypto", "election", "president",
            "chatgpt", "openai", "ai ", "trump", "biden",
        ])
        if has_vs and not non_sports_vs:
            return max(keyword_score, 0.8)

        strong_signals = ["championship", "playoff", "super bowl", "world cup", "world series", "grand slam"]
        has_strong = any(s in title_lower for s in strong_signals)
        if has_strong:
            return max(keyword_score, 0.85)

        # "Will X win on YYYY-MM-DD?" pattern
        has_win_date = bool(re.search(r"\bwin\b.*\d{4}-\d{2}-\d{2}", market.title, re.IGNORECASE))
        if has_win_date:
            return max(keyword_score, 0.75)

        return keyword_score


plugin = SportsPlugin()
