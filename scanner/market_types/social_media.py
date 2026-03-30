"""Social media market type module.

Handles markets like "Will Elon Musk post 200+ tweets this week?"
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from scanner.utils import count_matches

if TYPE_CHECKING:
    from scanner.models import Market


class SocialMedia:
    """Market type module for social media activity prediction markets."""

    name = "social_media"

    def classify(self, market: Market, keywords: list[str]) -> float:
        """Classify based on keywords + post/tweet count patterns."""
        keyword_score = min(1.0, count_matches(market.title, keywords) / 2.0) if keywords else 0.0

        title_lower = market.title.lower()
        # "post X-Y tweets/posts from..." or "X tweets" pattern
        has_post_count = bool(re.search(r"\bposts?\b.*\d+-?\d*\b.*\bfrom\b", title_lower))
        has_tweet_count = bool(re.search(r"\btweets?\b.*\d+", title_lower))
        if has_post_count or has_tweet_count:
            return max(keyword_score, 0.85)

        strong_signals = ["truth social", "x.com", "twitter"]
        has_strong = any(s in title_lower for s in strong_signals)
        if has_strong:
            return max(keyword_score, 0.7)

        return keyword_score


module = SocialMedia()
