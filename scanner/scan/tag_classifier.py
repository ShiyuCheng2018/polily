"""Classify events from Polymarket tags.

Two independent mappings, same tag source:

- `TAG_TYPE_MAP` / `classify_from_tags` → internal `market_type` used for
  per-type scoring weights (crypto, political, sports, ...).

- `TAG_TO_POLYMARKET_CATEGORY` / `infer_polymarket_category` → Polymarket's
  fee-curve category key (Crypto, Geopolitics, Politics, ...). Needed as a
  fallback when Gamma omits the top-level `category` field — observed in
  the real "US x Iran peace deal" event where Gamma returned only tags,
  leaving fees to default to 0.05 instead of the correct Geopolitics 0.0.
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


# Ordered (priority highest → lowest). Each entry maps a tag label to a
# Polymarket fee-curve category (see `scanner.core.fees.CATEGORY_FEE_RATES`).
# Order matters: Geopolitics wins over Politics when both are present
# (Polymarket's UI treats Geopolitics as its own category with 0% fee —
# conflating it with Politics would overcharge the user).
_POLYMARKET_CATEGORY_PRIORITY: list[tuple[str, str]] = [
    # 0% fee categories first — most favorable to the user when ambiguous.
    ("Geopolitics", "Geopolitics"),
    ("World Events", "World Events"),
    # High-fee categories.
    ("Crypto", "Crypto"),
    ("Bitcoin", "Crypto"),
    ("Ethereum", "Crypto"),
    # 4% categories.
    ("Sports", "Sports"),
    ("Soccer", "Sports"),
    ("Basketball", "Sports"),
    ("Football", "Sports"),
    ("Baseball", "Sports"),
    ("Tennis", "Sports"),
    ("Hockey", "Sports"),
    ("MMA", "Sports"),
    ("Boxing", "Sports"),
    ("Cricket", "Sports"),
    ("AI", "Tech"),
    ("Technology", "Tech"),
    # 5% categories.
    ("Economics", "Economics"),
    ("Federal Reserve", "Economics"),
    ("Inflation", "Economics"),
    ("Weather", "Weather"),
    ("Culture", "Culture"),
    # Politics comes AFTER Geopolitics so the zero-fee path wins when both
    # tags are present (common in foreign-affairs events).
    ("Politics", "Politics"),
    ("Elections", "Politics"),
    ("Congress", "Politics"),
    # Social / Mentions — Polymarket groups these as "Mentions" for fees.
    ("Social Media", "Mentions"),
    ("Twitter", "Mentions"),
]


def classify_from_tags(tags: list[str]) -> str:
    """Map Polymarket event tags to internal market type.

    Returns 'other' if no tag matches.
    """
    for tag in tags:
        market_type = TAG_TYPE_MAP.get(tag)
        if market_type:
            return market_type
    return "other"


def infer_polymarket_category(tags: list[str]) -> str | None:
    """Map tags to a Polymarket fee-curve category, or None if nothing matches.

    Used only as a fallback when Gamma's top-level `category` field is missing
    or empty. Returns None so the caller can keep a prior value / accept the
    default fee rate — does not pick "Other" silently.
    """
    tag_set = set(tags)
    for tag, category in _POLYMARKET_CATEGORY_PRIORITY:
        if tag in tag_set:
            return category
    return None
