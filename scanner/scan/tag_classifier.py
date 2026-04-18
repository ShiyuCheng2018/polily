"""Classify events from Polymarket tags.

`classify_from_tags` maps raw tags (e.g., "Bitcoin", "Soccer", "Geopolitics")
to our internal `market_type` enum used by scoring weights and agent prompt
branching. Polymarket's vocabulary is much finer (hundreds of tags) than
what scoring needs (~6 buckets), so this is the bucketing layer.

Fees are NOT driven by tags — they come from market-level `fees_enabled` +
`feeSchedule.rate` on the Gamma response (see `scanner.core.fees`).
"""

# Tag -> market_type mapping. First match wins.
TAG_TYPE_MAP: dict[str, str] = {
    # Crypto
    "Crypto": "crypto",
    "Bitcoin": "crypto",
    "Ethereum": "crypto",
    # Sports
    "Sports": "sports",
    "Soccer": "sports",
    "Basketball": "sports",
    "Football": "sports",
    "Baseball": "sports",
    "Tennis": "sports",
    "Hockey": "sports",
    "MMA": "sports",
    "Boxing": "sports",
    "Cricket": "sports",
    # Politics
    "Politics": "political",
    "Elections": "political",
    "Geopolitics": "political",
    "Congress": "political",
    # Economics
    "Economics": "economic_data",
    "Federal Reserve": "economic_data",
    "Inflation": "economic_data",
    # Tech
    "AI": "tech",
    "Technology": "tech",
    # Social media
    "Social Media": "social_media",
    "Twitter": "social_media",
}


def classify_from_tags(tags: list[str]) -> str:
    """Map Polymarket event tags to internal market type.

    Returns 'other' if no tag matches.
    """
    for tag in tags:
        market_type = TAG_TYPE_MAP.get(tag)
        if market_type:
            return market_type
    return "other"
