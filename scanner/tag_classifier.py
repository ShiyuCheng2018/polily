"""Classify market type from Polymarket event tags."""

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
