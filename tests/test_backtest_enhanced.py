"""Tests for enhanced backtest: friction-adjusted PnL, by-tier, by-score-range."""

import json
import tempfile
from pathlib import Path

import pytest

from scanner.backtest import run_backtest

# Archives with structure_score (new key name)
ARCHIVE = [
    {"market_id": "m1", "title": "BTC 88K", "structure_score": 82, "yes_price": 0.40,
     "mispricing_signal": "moderate", "market_type": "crypto_threshold",
     "round_trip_friction_pct": 0.04},
    {"market_id": "m2", "title": "CPI 3.5%", "structure_score": 76, "yes_price": 0.55,
     "mispricing_signal": "none", "market_type": "economic_data",
     "round_trip_friction_pct": 0.06},
    {"market_id": "m3", "title": "Fed rate", "structure_score": 68, "yes_price": 0.38,
     "mispricing_signal": "weak", "market_type": "economic_data",
     "round_trip_friction_pct": 0.05},
    {"market_id": "m4", "title": "ETH 2100", "structure_score": 85, "yes_price": 0.60,
     "mispricing_signal": "strong", "market_type": "crypto_threshold",
     "round_trip_friction_pct": 0.03},
]

RESOLUTIONS = {"m1": "yes", "m2": "no", "m3": "yes", "m4": "yes"}


@pytest.fixture
def archive_dir():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d)
        with open(p / "20260328.json", "w") as f:
            json.dump(ARCHIVE, f)
        yield p


class TestFrictionAdjustedBacktest:
    def test_has_friction_adjusted_pnl(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        assert result.friction_adjusted_pnl is not None
        assert result.friction_adjusted_pnl < result.naive_yes_pnl  # friction eats profit

    def test_friction_is_subtracted(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        # friction_adjusted should be naive minus total friction cost
        assert result.friction_adjusted_pnl < result.naive_yes_pnl

    def test_by_score_range(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        assert result.by_score_range is not None
        assert len(result.by_score_range) > 0

    def test_high_score_vs_low_score(self, archive_dir):
        result = run_backtest(archive_dir, RESOLUTIONS)
        ranges = list(result.by_score_range.keys())
        assert any("80" in r or "90" in r for r in ranges)
        assert any("60" in r or "70" in r for r in ranges)


class TestDirectionalBacktest:
    def test_directional_trades_with_mispricing_details(self):
        archive_data = [
            {"market_id": "d1", "title": "BTC 88K", "structure_score": 82, "yes_price": 0.60,
             "mispricing_signal": "moderate", "market_type": "crypto_threshold",
             "round_trip_friction_pct": 0.04,
             "mispricing_details": "Model est. 0.50, market 0.60, dev 10% — YES appears overpriced"},
            {"market_id": "d2", "title": "ETH 2100", "structure_score": 78, "yes_price": 0.35,
             "mispricing_signal": "strong", "market_type": "crypto_threshold",
             "round_trip_friction_pct": 0.03,
             "mispricing_details": "Model est. 0.45, market 0.35, dev 10% — YES appears underpriced"},
        ]
        resolutions = {"d1": "no", "d2": "yes"}  # d1: overpriced YES → buy NO → correct. d2: underpriced YES → buy YES → correct.

        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with open(p / "20260328.json", "w") as f:
                json.dump(archive_data, f)
            result = run_backtest(p, resolutions)

        assert result.directional_trades == 2
        assert result.directional_wins == 2  # both correct
        assert result.directional_pnl > 0

    def test_directional_via_structured_field(self):
        """Test that structured mispricing_direction is preferred over string parsing."""
        archive_data = [
            {"market_id": "s1", "title": "BTC", "structure_score": 80, "yes_price": 0.60,
             "mispricing_signal": "moderate", "market_type": "crypto_threshold",
             "round_trip_friction_pct": 0.04,
             "mispricing_direction": "overpriced"},  # structured field, no details text
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with open(p / "20260328.json", "w") as f:
                json.dump(archive_data, f)
            result = run_backtest(p, {"s1": "no"})  # overpriced → buy NO → NO wins
        assert result.directional_trades == 1
        assert result.directional_wins == 1

    def test_no_directional_trades_without_details(self):
        archive_data = [
            {"market_id": "n1", "structure_score": 70, "yes_price": 0.50,
             "mispricing_signal": "none", "market_type": "other",
             "round_trip_friction_pct": 0.04},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            with open(p / "20260328.json", "w") as f:
                json.dump(archive_data, f)
            result = run_backtest(p, {"n1": "yes"})

        assert result.directional_trades == 0
