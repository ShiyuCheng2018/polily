"""Tests for terminal rendering functions."""

from scanner.daily_briefing import MarketDelta
from scanner.render import _delta_context, render_candidate_simple
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


class TestRenderCandidateSimple:
    def test_contains_link(self):
        c = _make_candidate(market_id="test-id-123")
        output = render_candidate_simple(1, c)
        assert "polymarket.com/event/test-id-123" in output

    def test_cost_level_low(self):
        m = make_market(best_bid_yes=0.548, best_ask_yes=0.552)  # ~0.7% spread → ~1.5% round-trip
        c = ScoredCandidate(
            market=m,
            score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
            mispricing=MispricingResult(signal="none"),
        )
        output = render_candidate_simple(1, c)
        assert "低" in output

    def test_cost_level_high(self):
        m = make_market(best_bid_yes=0.40, best_ask_yes=0.60)
        c = ScoredCandidate(
            market=m,
            score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
            mispricing=MispricingResult(signal="none"),
        )
        output = render_candidate_simple(1, c)
        assert "偏高" in output


class TestScoreExplanation:
    def test_high_liquidity_shows_reason(self):
        c = ScoredCandidate(
            market=make_market(),
            score=ScoreBreakdown(22, 20, 16, 12, 8, total=78),
            mispricing=MispricingResult(signal="none"),
        )
        output = render_candidate_simple(1, c)
        assert "流动性好" in output

    def test_all_low_shows_fallback(self):
        c = ScoredCandidate(
            market=make_market(),
            score=ScoreBreakdown(5, 5, 5, 3, 2, total=20),
            mispricing=MispricingResult(signal="none"),
        )
        output = render_candidate_simple(1, c)
        assert "综合表现不错" in output


class TestDeltaContext:
    def test_big_move(self):
        d = MarketDelta(
            market_id="m1", title="T", yesterday_price=0.40, today_price=0.50,
            price_change_pct=0.25, yesterday_score=80, today_score=82,
            yesterday_mispricing="none", today_mispricing="none",
        )
        assert "Big move" in _delta_context(d)

    def test_notable(self):
        d = MarketDelta(
            market_id="m1", title="T", yesterday_price=0.50, today_price=0.54,
            price_change_pct=0.08, yesterday_score=80, today_score=82,
            yesterday_mispricing="none", today_mispricing="none",
        )
        assert "Notable" in _delta_context(d)

    def test_stable(self):
        d = MarketDelta(
            market_id="m1", title="T", yesterday_price=0.50, today_price=0.50,
            price_change_pct=0.005, yesterday_score=80, today_score=80,
            yesterday_mispricing="none", today_mispricing="none",
        )
        assert "Stable" in _delta_context(d)
