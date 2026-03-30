"""Tests for daily briefing: yesterday tracking, deltas, tier upgrades."""

import json
import tempfile
from pathlib import Path

import pytest

from scanner.daily_briefing import (
    DailyBriefing,
    compute_deltas,
    generate_briefing,
    load_latest_archives,
)

YESTERDAY_SCAN = [
    {
        "market_id": "m1",
        "title": "BTC above $88K?",
        "structure_score": 82,
        "yes_price": 0.42,
        "mispricing_signal": "moderate",
    },
    {
        "market_id": "m2",
        "title": "CPI exceed 3.5%?",
        "structure_score": 76,
        "yes_price": 0.55,
        "mispricing_signal": "none",
    },
]

TODAY_SCAN = [
    {
        "market_id": "m1",
        "title": "BTC above $88K?",
        "structure_score": 80,
        "yes_price": 0.48,
        "mispricing_signal": "weak",
    },
    {
        "market_id": "m2",
        "title": "CPI exceed 3.5%?",
        "structure_score": 78,
        "yes_price": 0.58,
        "mispricing_signal": "moderate",
    },
    {
        "market_id": "m3",
        "title": "Fed rate cut May?",
        "structure_score": 71,
        "yes_price": 0.38,
        "mispricing_signal": "none",
    },
]


@pytest.fixture
def archive_dir():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        with open(p / "20260327_220000.json", "w") as f:
            json.dump(YESTERDAY_SCAN, f)
        with open(p / "20260328_220000.json", "w") as f:
            json.dump(TODAY_SCAN, f)
        yield p


class TestLoadLatestArchives:
    def test_loads_two_most_recent(self, archive_dir):
        today, yesterday = load_latest_archives(archive_dir)
        assert today is not None
        assert yesterday is not None
        assert len(today) == 3
        assert len(yesterday) == 2

    def test_single_archive(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with open(p / "20260328.json", "w") as f:
                json.dump(TODAY_SCAN, f)
            today, yesterday = load_latest_archives(p)
            assert today is not None
            assert yesterday is None

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            today, yesterday = load_latest_archives(Path(d))
            assert today is None
            assert yesterday is None


class TestComputeDeltas:
    def test_price_change(self):
        deltas = compute_deltas(TODAY_SCAN, YESTERDAY_SCAN)
        m1_delta = next(d for d in deltas if d.market_id == "m1")
        assert m1_delta.yesterday_price == 0.42
        assert m1_delta.today_price == 0.48
        assert m1_delta.price_change_pct == pytest.approx((0.48 - 0.42) / 0.42, rel=0.01)

    def test_score_change(self):
        deltas = compute_deltas(TODAY_SCAN, YESTERDAY_SCAN)
        m1_delta = next(d for d in deltas if d.market_id == "m1")
        assert m1_delta.yesterday_score == 82
        assert m1_delta.today_score == 80

    def test_new_market_not_in_deltas(self):
        deltas = compute_deltas(TODAY_SCAN, YESTERDAY_SCAN)
        ids = [d.market_id for d in deltas]
        # m3 is new in today, should not appear as delta (no yesterday baseline)
        assert "m3" not in ids

    def test_disappeared_market(self):
        """Market in yesterday but not today — should show as disappeared."""
        yesterday = [{"market_id": "old", "title": "Gone", "structure_score": 70, "yes_price": 0.50, "mispricing_signal": "none"}]
        today = []
        deltas = compute_deltas(today, yesterday)
        assert len(deltas) == 1
        assert deltas[0].today_price is None
        assert deltas[0].disappeared is True

    def test_empty_inputs(self):
        assert compute_deltas([], []) == []


class TestGenerateBriefing:
    def test_briefing_has_all_sections(self, archive_dir):
        briefing = generate_briefing(archive_dir)
        assert isinstance(briefing, DailyBriefing)
        assert briefing.deltas is not None
        assert isinstance(briefing.new_markets, list)
        assert isinstance(briefing.summary, str)

    def test_briefing_identifies_new_markets(self, archive_dir):
        briefing = generate_briefing(archive_dir)
        new_ids = [m["market_id"] for m in briefing.new_markets]
        assert "m3" in new_ids

    def test_briefing_with_no_archives(self):
        with tempfile.TemporaryDirectory() as d:
            briefing = generate_briefing(Path(d))
            assert briefing.summary == "No scan archives found."
