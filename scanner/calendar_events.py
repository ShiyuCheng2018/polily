"""Event calendar: load upcoming events, match to markets, cross-domain linking."""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import yaml

from scanner.models import Market
from scanner.utils import matches_any

logger = logging.getLogger(__name__)

CROSS_DOMAIN_LINKS: dict[tuple[str, str], str] = {
    ("economic_data", "crypto_threshold"): (
        "Macro data releases often move crypto. Hot inflation → risk-off → crypto down."
    ),
    ("political", "crypto_threshold"): (
        "Regulatory/policy announcements can cause sharp crypto repricing."
    ),
    ("economic_data", "political"): (
        "Economic conditions influence policy expectations and vice versa."
    ),
}


@dataclass
class CalendarEvent:
    date: str  # ISO date string YYYY-MM-DD
    type: str  # "economic_data", "crypto", "tech", "political", etc.
    name: str
    impact: str = "medium"  # "high", "medium", "low"
    keywords: list[str] = field(default_factory=list)
    note: str | None = None


def load_calendar(path: Path) -> list[CalendarEvent]:
    """Load calendar events from YAML file."""
    if not path.exists():
        logger.warning("Calendar file not found: %s", path)
        return []
    try:
        with open(path) as f:
            data = yaml.safe_load(f)
        if not data or "events" not in data:
            return []
        return [CalendarEvent(**e) for e in data["events"]]
    except Exception as e:
        logger.warning("Failed to load calendar: %s", e)
        return []


def find_upcoming_events(
    events: list[CalendarEvent],
    now: datetime,
    lookahead_days: int = 3,
) -> list[CalendarEvent]:
    """Filter events within the lookahead window from now."""
    cutoff = now + timedelta(days=lookahead_days)
    upcoming = []
    for event in events:
        try:
            event_date = datetime.strptime(event.date, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError:
            continue
        if now <= event_date <= cutoff:
            upcoming.append(event)
    return upcoming


def match_markets_to_events(
    markets: list[Market],
    events: list[CalendarEvent],
) -> list[tuple[Market, CalendarEvent]]:
    """Match markets to upcoming events by keyword overlap."""
    matches = []
    for market in markets:
        for event in events:
            if matches_any(market.title, event.keywords):
                matches.append((market, event))
                break
    return matches


def generate_cross_domain_notes(
    market_event_pairs: list[tuple[Market, CalendarEvent]],
) -> list[str]:
    """Generate cross-domain insight notes when event type differs from market type."""
    notes = []
    for market, event in market_event_pairs:
        market_type = market.market_type or "other"
        event_type = event.type
        if market_type == event_type:
            continue
        key = (event_type, market_type)
        if key in CROSS_DOMAIN_LINKS:
            notes.append(
                f"[{event.name}] × [{market.title[:50]}]: {CROSS_DOMAIN_LINKS[key]}"
            )
    return notes
