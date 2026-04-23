"""Parse Polymarket URLs to extract event slugs."""

import re


def parse_polymarket_url(url_or_slug: str) -> str | None:
    """Extract event slug from a Polymarket URL or bare slug.

    Supports:
      - https://polymarket.com/event/{slug}
      - https://polymarket.com/event/{slug}/{market-slug}
      - polymarket.com/event/{slug}
      - {slug} (bare)

    Returns slug string or None if invalid.
    """
    if not url_or_slug or not url_or_slug.strip():
        return None

    url_or_slug = url_or_slug.strip()

    m = re.search(r'polymarket\.com/event/([^/?#]+)', url_or_slug)
    if m:
        return m.group(1)

    if '.' not in url_or_slug and '/' not in url_or_slug and len(url_or_slug) > 3:
        return url_or_slug

    return None
