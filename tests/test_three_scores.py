"""Tests for three-score system: market quality, trade value, direction edge."""

from scanner.mispricing import MispricingResult
from scanner.scoring import ScoreBreakdown, compute_three_scores
from tests.conftest import make_market


class TestComputeThreeScores:
    def test_returns_three_scores(self):
        s = ScoreBreakdown(20, 18, 16, 12, 8, total=74)
        mp = MispricingResult(signal="moderate", deviation_pct=0.06)
        m = make_market(yes_price=0.55)
        result = compute_three_scores(s, mp, m)
        assert "quality" in result
        assert "value" in result
        assert "edge" in result

    def test_quality_from_structure(self):
        s = ScoreBreakdown(28, 23, 18, 14, 9, total=92)
        mp = MispricingResult(signal="none")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["quality"] > 80

    def test_value_positive_when_edge_gt_friction(self):
        s = ScoreBreakdown(20, 18, 16, 12, 8, total=74)
        mp = MispricingResult(signal="strong", deviation_pct=0.10)
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)  # friction ~7%
        result = compute_three_scores(s, mp, m)
        # edge 10% - friction 7% = net 3% -> value ~27
        assert result["value"] > 20

    def test_value_uses_structural_when_no_quant_edge(self):
        """No mispricing model -> structural value kicks in."""
        s = ScoreBreakdown(20, 18, 16, 12, 8, total=74)
        mp = MispricingResult(signal="none", deviation_pct=0)
        m = make_market()  # yes=0.55, bid depth $1300, spread ~3.6%
        result = compute_three_scores(s, mp, m)
        # Structural value: probability sweet spot + some depth + time window
        assert result["value"] > 30  # structural value is nonzero

    def test_value_lower_for_bad_structure(self):
        """Bad structure -> lower structural value."""
        s = ScoreBreakdown(5, 3, 2, 3, 1, total=14)
        mp = MispricingResult(signal="none", deviation_pct=0)
        m_bad = make_market(
            yes_price=0.95,  # extreme probability
            best_bid_yes=0.94, best_ask_yes=0.96,
            book_depth_bids=None, book_depth_asks=None,
        )
        m_good = make_market()  # default: 0.55, good depth, good spread
        bad_val = compute_three_scores(s, mp, m_bad)["value"]
        good_val = compute_three_scores(s, mp, m_good)["value"]
        assert bad_val < good_val

    def test_value_prefers_quant_when_higher(self):
        """Quantitative value beats structural when edge is large."""
        s = ScoreBreakdown(20, 18, 16, 12, 8, total=74)
        mp = MispricingResult(signal="strong", deviation_pct=0.15)
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)  # friction ~7%
        result = compute_three_scores(s, mp, m)
        # net edge 15%-7% = 8%, quant value = 80, likely > structural
        assert result["value"] >= 65

    def test_edge_none_by_default(self):
        """Direction edge is None unless bias data available."""
        s = ScoreBreakdown(20, 18, 16, 12, 8, total=74)
        mp = MispricingResult(signal="none")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["edge"] is None

    def test_edge_from_mispricing_direction(self):
        s = ScoreBreakdown(20, 18, 16, 12, 8, total=74)
        mp = MispricingResult(signal="moderate", deviation_pct=0.06, direction="underpriced", model_confidence="high")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert result["edge"] is not None
        assert result["edge"] > 40

    def test_all_scores_bounded(self):
        s = ScoreBreakdown(28, 23, 18, 14, 9, total=92)
        mp = MispricingResult(signal="strong", deviation_pct=0.15, direction="underpriced", model_confidence="high")
        m = make_market()
        result = compute_three_scores(s, mp, m)
        assert 0 <= result["quality"] <= 100
        assert 0 <= result["value"] <= 100
        if result["edge"] is not None:
            assert 0 <= result["edge"] <= 100
