"""Tests for structure score computation."""

from datetime import UTC, datetime

from polily.core.models import BookLevel
from polily.scan.scoring import compute_structure_score
from tests.conftest import make_market


class TestStructureScore:
    def test_score_is_0_to_100(self):
        m = make_market()
        result = compute_structure_score(m)
        assert 0 <= result.total <= 100

    def test_perfect_market_scores_high(self):
        """A market with ideal properties should score > 60."""
        m = make_market(
            yes_price=0.50,
            best_bid_yes=0.495,
            best_ask_yes=0.505,
            volume=100000,
            open_interest=80000,
            resolution_source="Binance",
            rules="This market resolves YES if BTC price exceeds $88,000 on March 30 2026 per Binance spot data. The resolution source is Binance official spot price.",
            resolution_time=datetime(2026, 3, 31, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),
            book_depth_bids=[BookLevel(price=0.49, size=2000), BookLevel(price=0.48, size=3000)],
            book_depth_asks=[BookLevel(price=0.51, size=2000), BookLevel(price=0.52, size=3000)],
        )
        result = compute_structure_score(m)
        assert result.total >= 60

    def test_bad_market_scores_low(self):
        """A market with poor properties should score < 30."""
        m = make_market(
            yes_price=0.92,
            best_bid_yes=0.85,
            best_ask_yes=0.99,
            volume=2000,
            resolution_source=None,
            rules=None,
            resolution_time=datetime(2026, 4, 15, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),
            book_depth_bids=[BookLevel(price=0.85, size=50)],
            book_depth_asks=[BookLevel(price=0.99, size=50)],
        )
        result = compute_structure_score(m)
        assert result.total < 30

    def test_breakdown_has_all_components(self):
        m = make_market()
        result = compute_structure_score(m)
        assert result.liquidity_structure >= 0
        assert result.objective_verifiability >= 0
        assert result.probability_space >= 0
        assert result.time_structure >= 0
        assert result.trading_friction >= 0

    def test_breakdown_sums_to_total(self):
        m = make_market()
        result = compute_structure_score(m)
        component_sum = (
            result.liquidity_structure + result.objective_verifiability
            + result.probability_space + result.time_structure
            + result.trading_friction
        )
        assert abs(component_sum - result.total) < 0.01

    def test_mid_probability_scores_higher(self):
        m_mid = make_market(yes_price=0.50)
        m_edge = make_market(yes_price=0.22)
        s_mid = compute_structure_score(m_mid)
        s_edge = compute_structure_score(m_edge)
        assert s_mid.probability_space > s_edge.probability_space

    def test_tighter_spread_scores_higher(self):
        m_tight = make_market(best_bid_yes=0.545, best_ask_yes=0.555)
        m_wide = make_market(best_bid_yes=0.50, best_ask_yes=0.60)
        s_tight = compute_structure_score(m_tight)
        s_wide = compute_structure_score(m_wide)
        assert s_tight.liquidity_structure > s_wide.liquidity_structure

    def test_low_yes_market_not_penalized_for_yes_side_spread_pct(self):
        """A 25¢ YES market with 1¢ spread has 4.08% on YES side but only
        1.32% on NO side. Liquidity scoring must use the best side or it
        unfairly penalizes every market below 50¢ YES.
        """
        # Low-YES market with a real 1¢ spread (tight).
        m_low_yes = make_market(best_bid_yes=0.24, best_ask_yes=0.25)
        # Symmetric 50¢ market with the same 1¢ spread.
        m_mid = make_market(best_bid_yes=0.495, best_ask_yes=0.505)
        s_low = compute_structure_score(m_low_yes)
        s_mid = compute_structure_score(m_mid)
        # Both should land in the same spread tier on the liquidity dimension.
        # (They won't be exactly equal because yes_price also shifts other
        #  dimensions, but the spread component alone should be comparable.)
        assert s_low.liquidity_structure >= s_mid.liquidity_structure - 0.5

    def test_deeper_book_scores_higher(self):
        m_deep = make_market(
            book_depth_bids=[BookLevel(price=0.54, size=5000), BookLevel(price=0.53, size=5000)],
            book_depth_asks=[BookLevel(price=0.56, size=5000), BookLevel(price=0.57, size=5000)],
        )
        m_shallow = make_market(
            book_depth_bids=[BookLevel(price=0.54, size=50)],
            book_depth_asks=[BookLevel(price=0.56, size=50)],
        )
        s_deep = compute_structure_score(m_deep)
        s_shallow = compute_structure_score(m_shallow)
        assert s_deep.liquidity_structure > s_shallow.liquidity_structure

    def test_no_depth_data_lower_liquidity(self):
        m_with = make_market()
        m_without = make_market(book_depth_bids=None, book_depth_asks=None)
        s_with = compute_structure_score(m_with)
        s_without = compute_structure_score(m_without)
        assert s_with.liquidity_structure > s_without.liquidity_structure

    def test_objective_baseline_zero(self):
        """Market with no resolution data should score 0 on objectivity."""
        m = make_market(resolution_source=None, rules=None, description=None)
        s = compute_structure_score(m)
        # Only title-based score possible, but title has "above" which matches objective signals
        # Baseline is 0, so even with title bonus it should be low
        assert s.objective_verifiability < 15  # less than 60% of max (25)

    def test_good_resolution_source_boosts_objectivity(self):
        m_good = make_market(
            resolution_source="Binance official spot price",
            rules="Resolves YES if BTC exceeds $88,000 on March 30 per Binance. Clear binary outcome.",
        )
        m_bad = make_market(resolution_source=None, rules=None, description=None)
        s_good = compute_structure_score(m_good)
        s_bad = compute_structure_score(m_bad)
        assert s_good.objective_verifiability > s_bad.objective_verifiability

    def test_time_sweet_spot(self):
        """Markets in [1,5] day window should score higher on time."""
        m_sweet = make_market(
            resolution_time=datetime(2026, 3, 30, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),  # 2 days
        )
        m_far = make_market(
            resolution_time=datetime(2026, 4, 10, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, tzinfo=UTC),  # 13 days
        )
        s_sweet = compute_structure_score(m_sweet)
        s_far = compute_structure_score(m_far)
        assert s_sweet.time_structure > s_far.time_structure

    def test_friction_tiers(self):
        """Lower friction should score higher."""
        m_low = make_market(best_bid_yes=0.545, best_ask_yes=0.555)  # ~1.8% friction
        m_high = make_market(best_bid_yes=0.50, best_ask_yes=0.60)  # ~36% friction
        s_low = compute_structure_score(m_low)
        s_high = compute_structure_score(m_high)
        assert s_low.trading_friction > s_high.trading_friction
