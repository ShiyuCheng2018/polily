"""Tests for hard filters."""

from datetime import UTC, datetime

from polily.core.config import FiltersConfig, HeuristicsConfig
from polily.scan.filters import apply_hard_filters
from tests.conftest import make_market


def _default_filters() -> FiltersConfig:
    return FiltersConfig()


def _default_heuristics() -> HeuristicsConfig:
    return HeuristicsConfig(
        noise_market_keywords=["5 min", "5-minute", "up or down"],
        noise_max_days=0.1,
        noise_categories=["Crypto"],
        narrative_market_keywords=["best ai model", "most valuable"],
    )


class TestProbabilityFilter:
    def test_pass_mid_probability(self):
        m = make_market(yes_price=0.55)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_reject_extreme_low(self):
        m = make_market(yes_price=0.10)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0
        assert "probability" in result.rejected[0].reason.lower()

    def test_reject_extreme_high(self):
        m = make_market(yes_price=0.90)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0

    def test_edge_of_acceptable(self):
        m = make_market(yes_price=0.20)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_just_below_hard_reject(self):
        m = make_market(yes_price=0.14)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0


class TestTimeFilter:
    def test_pass_2_days(self):
        m = make_market(
            resolution_time=datetime(2026, 3, 30, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),
        )
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_reject_too_far(self):
        m = make_market(
            resolution_time=datetime(2026, 5, 1, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),
        )
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0
        assert "resolution" in result.rejected[0].reason.lower()

    def test_pass_no_resolution_time(self):
        """Markets without resolution_time should be rejected (can't assess)."""
        m = make_market(resolution_time=None)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0


class TestSpreadFilter:
    def test_pass_tight_spread(self):
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_reject_wide_spread(self):
        m = make_market(best_bid_yes=0.40, best_ask_yes=0.60)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0

    def test_pass_low_yes_market_with_tradeable_no_side(self):
        """Iran-style: YES=24¢/25¢ (4% spread on YES side alone) but NO side
        only has 1.3% spread. Filter must use best-side so the market isn't
        rejected for something the user would never buy anyway.

        Pre-fix this would fail: spread_pct_yes=4.08% exceeds the 4% default
        threshold, so the whole market was dropped from scoring.
        """
        m = make_market(best_bid_yes=0.24, best_ask_yes=0.25)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_reject_when_both_sides_wide(self):
        """Genuinely wide market (both YES% and NO% over threshold) still rejected."""
        # YES=0.10/0.30 → spread_abs=0.20, mid_yes=0.20, mid_no=0.80
        # YES% = 100%, NO% = 25%. Best side (NO) = 25% > 4% default → reject.
        m = make_market(best_bid_yes=0.10, best_ask_yes=0.30)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0


class TestVolumeFilter:
    def test_pass_sufficient_volume(self):
        m = make_market(volume=50000)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_reject_low_volume(self):
        m = make_market(volume=500)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0


class TestBinaryFilter:
    """v0.5.0: binary filter removed — multi-outcome markets now pass through."""

    def test_pass_binary(self):
        m = make_market(outcomes=["Yes", "No"])
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_multi_outcome_also_passes(self):
        m = make_market(outcomes=["A", "B", "C"])
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1  # v0.5.0: no longer filtered


class TestNoiseMarketFilter:
    def test_reject_5min_keyword(self):
        m = make_market(title="BTC 5 min up or down?")
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0

    def test_pass_normal_market(self):
        m = make_market(title="Will BTC be above $88,000 on March 30?")
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1


class TestObjectivityFilter:
    def test_reject_subjective_keyword(self):
        h = _default_heuristics()
        h.objective_blacklist_keywords = ["best", "favorite", "strongest"]
        m = make_market(title="Who is the best AI model?")
        result = apply_hard_filters([m], _default_filters(), h)
        assert len(result.passed) == 0
        assert "subjective" in result.rejected[0].reason.lower()

    def test_pass_objective_market(self):
        h = _default_heuristics()
        h.objective_blacklist_keywords = ["best", "favorite"]
        m = make_market(title="Will BTC be above $88,000 on March 30?")
        result = apply_hard_filters([m], _default_filters(), h)
        assert len(result.passed) == 1


class TestOpenInterestFilter:
    def test_pass_sufficient_oi(self):
        m = make_market(open_interest=5000)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 1

    def test_reject_low_oi(self):
        m = make_market(open_interest=500)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0
        assert "open interest" in result.rejected[0].reason.lower()


class TestNoPriceFilter:
    def test_reject_no_yes_price(self):
        m = make_market(yes_price=None)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert len(result.passed) == 0


class TestFilterResult:
    def test_filter_result_counts(self):
        markets = [
            make_market(market_id="good", yes_price=0.55, volume=50000),
            make_market(market_id="bad_price", yes_price=0.05, volume=50000),
            make_market(market_id="bad_vol", yes_price=0.55, volume=100),
        ]
        result = apply_hard_filters(markets, _default_filters(), _default_heuristics())
        assert len(result.passed) == 1
        assert len(result.rejected) == 2

    def test_rejection_has_market_id_and_reason(self):
        m = make_market(market_id="0xbad", yes_price=0.05)
        result = apply_hard_filters([m], _default_filters(), _default_heuristics())
        assert result.rejected[0].market_id == "0xbad"
        assert len(result.rejected[0].reason) > 0
