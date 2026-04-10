"""Tests for --simple newbie-friendly output mode."""

from scanner.render import render_candidate_simple
from scanner.scan.mispricing import MispricingResult
from scanner.scan.reporting import ScoredCandidate
from scanner.scan.scoring import ScoreBreakdown
from tests.conftest import make_market


def _make_candidate(**overrides) -> ScoredCandidate:
    return ScoredCandidate(
        market=make_market(**{k: v for k, v in overrides.items()
                              if k in ("title", "yes_price", "market_type", "market_id")}),
        score=ScoreBreakdown(
            liquidity_structure=20, objective_verifiability=18,
            probability_space=16, time_structure=12,
            trading_friction=8, total=overrides.get("total", 74),
        ),
        mispricing=MispricingResult(signal="none"),
    )


class TestRenderSimple:
    def test_returns_string(self):
        c = _make_candidate()
        output = render_candidate_simple(1, c)
        assert isinstance(output, str)

    def test_contains_title(self):
        c = _make_candidate(title="Will BTC be above $88K?")
        output = render_candidate_simple(1, c)
        assert "BTC" in output

    def test_contains_score_with_explanation(self):
        c = _make_candidate(total=78)
        output = render_candidate_simple(1, c)
        assert "78" in output
        # Should have inline explanation
        assert "结构" in output or "structure" in output.lower() or "质量" in output

    def test_contains_cost_info(self):
        c = _make_candidate()
        output = render_candidate_simple(1, c)
        # Should mention cost/friction in user-friendly way
        assert "%" in output  # friction percentage

    def test_contains_time(self):
        c = _make_candidate()
        output = render_candidate_simple(1, c)
        assert "天" in output or "d" in output.lower()

    def test_does_not_contain_advanced_fields(self):
        """Simple mode should NOT show mispricing, exitability, order book details."""
        c = _make_candidate()
        output = render_candidate_simple(1, c)
        assert "exitability" not in output.lower()
        assert "imbalance" not in output.lower()
        assert "catalyst_proxy" not in output.lower()

    def test_contains_depth_simplified(self):
        c = _make_candidate()
        output = render_candidate_simple(1, c)
        # Should show simplified depth (enough/thin/insufficient), not raw numbers
        assert any(w in output for w in ["够用", "勉强", "不够", "depth"])
