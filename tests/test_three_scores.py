"""Tests for three-score system: market quality, trade value, direction edge."""

from scanner.mispricing import MispricingResult
from scanner.scoring import ScoreBreakdown, compute_three_scores
from tests.conftest import make_market


class TestComputeThreeScores:
    def test_returns_three_scores(self):
        s = ScoreBreakdown(12, 16, 16, 18, 7, 3, 8, total=80)
        mp = MispricingResult(signal="moderate", deviation_pct=0.06)
        m = make_market(yes_price=0.55)
        result = compute_three_scores(s, mp, m)
        assert "quality" in result
        assert "value" in result
        assert "edge" in result

    def test_quality_from_structure(self):
        s = ScoreBreakdown(15, 20, 20, 20, 10, 5, 10, total=100)
        mp = MispricingResult(signal="none")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["quality"] > 80

    def test_value_positive_when_edge_gt_friction(self):
        s = ScoreBreakdown(12, 16, 16, 18, 7, 3, 8, total=80)
        mp = MispricingResult(signal="strong", deviation_pct=0.10)
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)  # friction ~7%
        result = compute_three_scores(s, mp, m)
        # edge 10% - friction 7% = net 3% → value ~27
        assert result["value"] > 20

    def test_value_low_when_no_edge(self):
        s = ScoreBreakdown(12, 16, 16, 18, 7, 3, 8, total=80)
        mp = MispricingResult(signal="none", deviation_pct=0)
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["value"] < 30

    def test_value_low_when_friction_eats_edge(self):
        s = ScoreBreakdown(12, 16, 16, 18, 7, 3, 8, total=80)
        mp = MispricingResult(signal="weak", deviation_pct=0.02)
        m = make_market(best_bid_yes=0.50, best_ask_yes=0.60)  # friction ~40%
        result = compute_three_scores(s, mp, m)
        assert result["value"] < 30

    def test_edge_none_by_default(self):
        """Direction edge is None unless bias data available."""
        s = ScoreBreakdown(12, 16, 16, 18, 7, 3, 8, total=80)
        mp = MispricingResult(signal="none")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["edge"] is None

    def test_edge_from_mispricing_direction(self):
        s = ScoreBreakdown(12, 16, 16, 18, 7, 3, 8, total=80)
        mp = MispricingResult(signal="moderate", deviation_pct=0.06, direction="underpriced", model_confidence="high")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["edge"] is not None
        assert result["edge"] > 40

    def test_all_scores_bounded(self):
        s = ScoreBreakdown(15, 20, 20, 20, 10, 5, 10, total=100)
        mp = MispricingResult(signal="strong", deviation_pct=0.15, direction="underpriced", model_confidence="high")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert 0 <= result["quality"] <= 100
        assert 0 <= result["value"] <= 100
        if result["edge"] is not None:
            assert 0 <= result["edge"] <= 100
