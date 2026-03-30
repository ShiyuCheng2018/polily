"""Tests for reporting: tier classification, JSON output, terminal rendering."""

import json

from scanner.config import ScoringThresholds
from scanner.mispricing import MispricingResult
from scanner.reporting import (
    ScoredCandidate,
    classify_tiers,
    render_candidate_json,
)
from scanner.scoring import ScoreBreakdown
from tests.conftest import make_market


def _make_candidate(
    total: float = 80,
    mispricing_signal: str = "moderate",
    **market_overrides,
) -> ScoredCandidate:
    return ScoredCandidate(
        market=make_market(**market_overrides),
        score=ScoreBreakdown(
            time_to_resolution=12,
            objectivity=16,
            probability_zone=16,
            liquidity_depth=18,
            exitability=7,
            catalyst_proxy=3,
            small_account_friendliness=8,
            total=total,
        ),
        mispricing=MispricingResult(
            signal=mispricing_signal,
            theoretical_fair_value=0.49,
            deviation_pct=0.06,
            details="Model est. 0.49, market 0.55",
        ),
    )


class TestClassifyTiers:
    def _thresholds(self) -> ScoringThresholds:
        return ScoringThresholds(
            tier_a_min_score=75,
            tier_b_min_score=60,
            tier_a_require_mispricing=True,
        )

    def test_tier_a_high_score_with_mispricing(self):
        c = _make_candidate(total=80, mispricing_signal="moderate")
        result = classify_tiers([c], self._thresholds())
        assert len(result.tier_a) == 1
        assert len(result.tier_b) == 0

    def test_tier_b_high_score_no_mispricing(self):
        """High score but no mispricing -> Tier B (not A)."""
        c = _make_candidate(total=80, mispricing_signal="none")
        result = classify_tiers([c], self._thresholds())
        assert len(result.tier_a) == 0
        assert len(result.tier_b) == 1

    def test_tier_b_mid_score(self):
        c = _make_candidate(total=65, mispricing_signal="moderate")
        result = classify_tiers([c], self._thresholds())
        assert len(result.tier_a) == 0
        assert len(result.tier_b) == 1

    def test_tier_c_low_score(self):
        c = _make_candidate(total=50, mispricing_signal="none")
        result = classify_tiers([c], self._thresholds())
        assert len(result.tier_a) == 0
        assert len(result.tier_b) == 0
        assert len(result.tier_c) == 1

    def test_tiers_sorted_by_score(self):
        c1 = _make_candidate(total=82, mispricing_signal="strong", market_id="m1")
        c2 = _make_candidate(total=78, mispricing_signal="moderate", market_id="m2")
        c3 = _make_candidate(total=90, mispricing_signal="strong", market_id="m3")
        result = classify_tiers([c1, c2, c3], self._thresholds())
        assert result.tier_a[0].market.market_id == "m3"
        assert result.tier_a[1].market.market_id == "m1"

    def test_tier_a_without_mispricing_requirement(self):
        thresholds = ScoringThresholds(
            tier_a_min_score=75,
            tier_b_min_score=60,
            tier_a_require_mispricing=False,
        )
        c = _make_candidate(total=80, mispricing_signal="none")
        result = classify_tiers([c], thresholds)
        assert len(result.tier_a) == 1


class TestRenderCandidateJson:
    def test_json_output_valid(self):
        c = _make_candidate()
        output = render_candidate_json(c)
        parsed = json.loads(output)
        assert parsed["market_id"] == "0xtest"
        assert parsed["structure_score"] == 80

    def test_json_contains_breakdown(self):
        c = _make_candidate()
        output = render_candidate_json(c)
        parsed = json.loads(output)
        assert "structure_score_breakdown" in parsed
        assert parsed["structure_score_breakdown"]["objectivity"] == 16

    def test_json_contains_mispricing(self):
        c = _make_candidate()
        output = render_candidate_json(c)
        parsed = json.loads(output)
        assert parsed["mispricing_signal"] == "moderate"
        assert parsed["theoretical_fair_value"] == 0.49

    def test_json_contains_friction(self):
        c = _make_candidate()
        output = render_candidate_json(c)
        parsed = json.loads(output)
        assert "round_trip_friction_pct" in parsed
