"""Shared utility functions."""


def matches_any(text: str, keywords: list[str]) -> bool:
    """Check if text contains any of the keywords (case-insensitive)."""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in keywords)


def count_matches(text: str, keywords: list[str]) -> int:
    """Count how many keywords appear in text (case-insensitive)."""
    text_lower = text.lower()
    return sum(1 for kw in keywords if kw.lower() in text_lower)


def extract_market_id_from_prompt(prompt: str) -> str:
    """Extract market_id from a JSON prompt string. Returns 'unknown' if not found."""
    import re
    try:
        match = re.search(r'"market_id":\s*"([^"]+)"', prompt)
        if match:
            return match.group(1)
    except Exception:
        pass
    return "unknown"


def fmt(val: float | None, format_spec: str, default: str = "?") -> str:
    """Format a value if not None, else return default."""
    if val is None:
        return default
    return f"{val:{format_spec}}"
