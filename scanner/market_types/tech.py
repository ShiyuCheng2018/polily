"""Tech market type module.

Handles markets like "Will OpenAI release GPT-5 by June?"
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from scanner.utils import count_matches

if TYPE_CHECKING:
    from scanner.models import Market


class Tech:
    """Market type module for technology prediction markets."""

    name = "tech"

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Classify based on keywords + tech company/product patterns."""
        keyword_score = min(1.0, count_matches(market.title, keywords) / 2.0) if keywords else 0.0

        title_lower = market.title.lower()
        strong_signals = ["openai", "chatgpt", "gpt-", "nvidia", "tsmc", "apple wwdc", "google i/o"]
        has_strong = any(s in title_lower for s in strong_signals)
        if has_strong:
            return max(keyword_score, 0.8)

        return keyword_score


module = Tech()
