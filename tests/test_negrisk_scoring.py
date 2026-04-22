"""Test that negRisk spread fix produces reasonable scores.

After fixing bid/ask to come from /price instead of /book,
negRisk markets with real 1-2% spread should score much higher
on liquidity and friction dimensions than with 98% spread.
"""

import pytest

from polily.scan.scoring import compute_structure_score
from tests.conftest import make_market


class TestNegRiskScoringImprovement:
    def test_score_improvement_after_spread_fix(self):
        """negRisk market with real spread should score much higher than with raw /book spread."""
        # Before fix: /book returns bid=0.01, ask=0.99 → spread=0.98
        broken = make_market(
            best_bid_yes=0.01,
            best_ask_yes=0.99,
            spread_yes=0.98,
            yes_price=0.55,
        )

        # After fix: /price returns real bid=0.54, ask=0.56 → spread=0.02
        fixed = make_market(
            best_bid_yes=0.54,
            best_ask_yes=0.56,
            spread_yes=0.02,
            yes_price=0.55,
        )

        broken_score = compute_structure_score(broken)
        fixed_score = compute_structure_score(fixed)

        # Liquidity should be significantly higher with real spread
        assert fixed_score.liquidity_structure > broken_score.liquidity_structure
        # Friction should be significantly higher (lower friction = higher score)
        assert fixed_score.trading_friction > broken_score.trading_friction
        # Total score should be higher
        assert fixed_score.total > broken_score.total

        # The improvement should be substantial (not just marginal)
        assert fixed_score.total - broken_score.total > 5.0

    def test_fixed_negrisk_scores_comparable_to_normal_market(self):
        """After fix, negRisk market scores should be in the same ballpark as non-negRisk."""
        fixed_negrisk = make_market(
            best_bid_yes=0.54,
            best_ask_yes=0.56,
            spread_yes=0.02,
            yes_price=0.55,
        )

        normal_market = make_market(
            best_bid_yes=0.54,
            best_ask_yes=0.56,
            spread_yes=0.02,
            yes_price=0.55,
        )

        s1 = compute_structure_score(fixed_negrisk)
        s2 = compute_structure_score(normal_market)

        # Same spread → same liquidity and friction scores
        assert s1.liquidity_structure == pytest.approx(s2.liquidity_structure, abs=0.1)
        assert s1.trading_friction == pytest.approx(s2.trading_friction, abs=0.1)
