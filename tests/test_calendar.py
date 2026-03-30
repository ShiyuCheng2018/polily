"""Tests for event calendar and cross-domain linking."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from scanner.calendar_events import (
    CROSS_DOMAIN_LINKS,
    CalendarEvent,
    find_upcoming_events,
    generate_cross_domain_notes,
    load_calendar,
    match_markets_to_events,
)
from tests.conftest import make_market

SAMPLE_CALENDAR = [
    {
        "date": "2026-03-29",
        "type": "economic_data",
        "name": "CPI Release (February)",
        "impact": "high",
        "keywords": ["cpi", "inflation", "consumer price"],
        "note": "BLS releases at 8:30 AM ET.",
    },
    {
        "date": "2026-04-02",
        "type": "economic_data",
        "name": "FOMC Minutes",
        "impact": "medium",
        "keywords": ["fomc", "fed", "rate", "monetary policy"],
    },
    {
        "date": "2026-04-10",
        "type": "tech",
        "name": "NVIDIA GTC Keynote",
        "impact": "high",
        "keywords": ["nvidia", "ai", "gpu"],
    },
]


@pytest.fixture
def calendar_file():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({"events": SAMPLE_CALENDAR}, f)
        return Path(f.name)


class TestLoadCalendar:
    def test_load_valid_file(self, calendar_file):
        events = load_calendar(calendar_file)
        assert len(events) == 3
        assert events[0].name == "CPI Release (February)"
        assert events[0].impact == "high"

    def test_load_nonexistent_file(self):
        events = load_calendar(Path("/nonexistent/calendar.yaml"))
        assert events == []

    def test_event_has_all_fields(self, calendar_file):
        events = load_calendar(calendar_file)
        e = events[0]
        assert isinstance(e, CalendarEvent)
        assert e.date == "2026-03-29"
        assert e.type == "economic_data"
        assert "cpi" in e.keywords


class TestFindUpcomingEvents:
    def test_find_within_lookahead(self, calendar_file):
        events = load_calendar(calendar_file)
        now = datetime(2026, 3, 28, tzinfo=UTC)
        upcoming = find_upcoming_events(events, now, lookahead_days=3)
        # CPI on Mar 29 is within 3 days, FOMC on Apr 2 is within 5 days
        assert any(e.name == "CPI Release (February)" for e in upcoming)

    def test_exclude_past_events(self, calendar_file):
        events = load_calendar(calendar_file)
        now = datetime(2026, 4, 5, tzinfo=UTC)
        upcoming = find_upcoming_events(events, now, lookahead_days=3)
        # CPI and FOMC are past, only NVIDIA GTC (Apr 10) within 5 days
        assert not any(e.name == "CPI Release (February)" for e in upcoming)

    def test_empty_calendar(self):
        upcoming = find_upcoming_events([], datetime.now(UTC), lookahead_days=3)
        assert upcoming == []


class TestMatchMarketsToEvents:
    def test_match_cpi_market(self, calendar_file):
        events = load_calendar(calendar_file)
        now = datetime(2026, 3, 28, tzinfo=UTC)
        upcoming = find_upcoming_events(events, now, lookahead_days=3)

        market = make_market(title="Will CPI MoM exceed 0.4%?")
        matches = match_markets_to_events([market], upcoming)
        assert len(matches) > 0
        assert matches[0][1].name == "CPI Release (February)"

    def test_no_match(self, calendar_file):
        events = load_calendar(calendar_file)
        now = datetime(2026, 3, 28, tzinfo=UTC)
        upcoming = find_upcoming_events(events, now, lookahead_days=3)

        market = make_market(title="Will Lakers win NBA championship?")
        matches = match_markets_to_events([market], upcoming)
        assert len(matches) == 0


class TestCrossDomainNotes:
    def test_economic_data_cross_crypto(self):
        event = CalendarEvent(
            date="2026-03-29", type="economic_data", name="CPI Release",
            impact="high", keywords=["cpi"],
        )
        market = make_market(market_type="crypto_threshold")
        notes = generate_cross_domain_notes([(market, event)])
        assert len(notes) == 1
        assert "crypto" in notes[0].lower() or "risk" in notes[0].lower()

    def test_no_cross_domain_same_type(self):
        event = CalendarEvent(
            date="2026-03-29", type="economic_data", name="CPI",
            impact="high", keywords=["cpi"],
        )
        market = make_market(market_type="economic_data")
        notes = generate_cross_domain_notes([(market, event)])
        assert len(notes) == 0

    def test_cross_domain_links_exist(self):
        assert ("economic_data", "crypto_threshold") in CROSS_DOMAIN_LINKS
