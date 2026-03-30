"""Tests for backtest analyzer: compare historical scans vs actual resolutions."""

import json
import tempfile
from pathlib import Path

import pytest

from scanner.backtest import (
    BacktestResult,
    load_all_archives,
    run_backtest,
)

# Simulated archived scan: 3 markets, 2 resolved YES, 1 resolved NO
ARCHIVE_1 = [
    {
        "market_id": "m1",
        "title": "BTC above 88K?",
        "structure_score": 82,
        "yes_price": 0.42,
        "mispricing_signal": "moderate",
        "market_type": "crypto_threshold",
    },
    {
        "market_id": "m2",
        "title": "CPI exceed 3.5%?",
        "structure_score": 76,
        "yes_price": 0.55,
        "mispricing_signal": "none",
        "market_type": "economic_data",
    },
]

ARCHIVE_2 = [
    {
        "market_id": "m1",
        "title": "BTC above 88K?",
        "structure_score": 82,
        "yes_price": 0.48,
        "mispricing_signal": "moderate",
        "market_type": "crypto_threshold",
    },
    {
        "market_id": "m3",
        "title": "Fed rate cut?",
        "structure_score": 71,
        "yes_price": 0.38,
        "mispricing_signal": "weak",
        "market_type": "economic_data",
    },
]

# Resolution data: what actually happened
RESOLUTIONS = {
    "m1": "yes",
    "m2": "no",
    "m3": "yes",
}


@pytest.fixture
def archive_dir():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        with open(p / "20260327_220000.json", "w") as f:
            json.dump(ARCHIVE_1, f)
        with open(p / "20260328_220000.json", "w") as f:
            json.dump(ARCHIVE_2, f)
        yield p


class TestLoadAllArchives:
    def test_loads_all_scans(self, archive_dir):
        archives = load_all_archives(archive_dir)
        assert len(archives) == 2

    def test_empty_dir(self):
        with tempfile.TemporaryDirectory() as d:
            archives = load_all_archives(Path(d))
            assert archives == []


class TestRunBacktest:
    def test_basic_backtest(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        assert isinstance(result, BacktestResult)
        assert result.total_markets > 0
        assert result.resolved > 0

    def test_naive_yes_pnl(self, archive_dir):
        """If we bought YES on every scanned market, what's the PnL?"""
        result = run_backtest(archive_dir, RESOLUTIONS)
        # m1 YES at 0.42 → resolved YES → profit
        # m2 YES at 0.55 → resolved NO → loss
        # m3 YES at 0.38 → resolved YES → profit
        assert result.naive_yes_pnl != 0

    def test_by_mispricing_signal(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        # Should have stats grouped by mispricing signal
        assert "moderate" in result.by_mispricing_signal
        assert "none" in result.by_mispricing_signal

    def test_by_market_type(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        assert "crypto_threshold" in result.by_market_type

    def test_high_score_hit_rate(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        # Markets with score >= 75 vs < 75
        assert result.high_score_hit_rate is not None

    def test_no_resolutions(self, archive_dir):
        result = run_backtest(archive_dir, {})
        assert result.resolved == 0
        assert result.naive_yes_pnl == 0

    def test_empty_archives(self):
        with tempfile.TemporaryDirectory() as d:
            result = run_backtest(Path(d), RESOLUTIONS)
            assert result.total_markets == 0
