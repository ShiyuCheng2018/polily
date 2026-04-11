"""Tests for event-level quality scoring (5 dimensions)."""

from datetime import UTC, datetime, timedelta

from scanner.scan.event_scoring import EventQualityScore, compute_event_quality_score
from tests.conftest import make_event, make_market


def _make_markets(event_id="ev1", count=3, yes_prices=None, volumes=None,
                  bid_depths=None, spreads=None, resolution_days=7):
    """Build a list of markets for testing."""
    if yes_prices is None:
        yes_prices = [0.5, 0.3, 0.2][:count]
    if volumes is None:
        volumes = [50000] * count
    if bid_depths is None:
        bid_depths = [5000] * count
    if spreads is None:
        spreads = [0.02] * count

    res_time = datetime.now(UTC) + timedelta(days=resolution_days)
    markets = []
    for i in range(count):
        m = make_market(
            market_id=f"{event_id}_m{i}",
            event_id=event_id,
            yes_price=yes_prices[i] if i < len(yes_prices) else 0.1,
            volume=volumes[i] if i < len(volumes) else 10000,
            resolution_time=res_time,
        )
        # Set depth + spread (not set by make_market defaults in useful way)
        m.best_bid_yes = (yes_prices[i] if i < len(yes_prices) else 0.1) - 0.01
        m.best_ask_yes = (yes_prices[i] if i < len(yes_prices) else 0.1) + 0.01
        m.spread_yes = spreads[i] if i < len(spreads) else 0.02
        # Simulate book depth via BookLevel
        from scanner.core.models import BookLevel
        bd = bid_depths[i] if i < len(bid_depths) else 1000
        m.book_depth_bids = [BookLevel(price=0.5, size=bd)]
        m.book_depth_asks = [BookLevel(price=0.6, size=bd)]
        markets.append(m)
    return markets


class TestEventQualityScoreBasic:
    def test_returns_score_object(self):
        ev = make_event(event_id="ev1", volume=100000)
        mkts = _make_markets()
        score = compute_event_quality_score(ev, mkts)
        assert isinstance(score, EventQualityScore)
        assert 0 <= score.total <= 100

    def test_high_quality_event(self):
        """Good volume, balanced outcomes, decent depth, reasonable time."""
        ev = make_event(event_id="ev1", volume=500000,
                       resolution_source="https://official.com",
                       description="This market resolves based on official data from...")
        mkts = _make_markets(
            yes_prices=[0.35, 0.35, 0.30],
            volumes=[200000, 150000, 100000],
            bid_depths=[50000, 40000, 30000],
            spreads=[0.01, 0.01, 0.02],
            resolution_days=7,
        )
        score = compute_event_quality_score(ev, mkts)
        assert score.total >= 60  # should be a good score

    def test_low_quality_event(self):
        """Low volume, thin depth, wide spread."""
        ev = make_event(event_id="ev1", volume=6000)
        mkts = _make_markets(
            yes_prices=[0.95, 0.03, 0.02],
            volumes=[3000, 1000, 500],
            bid_depths=[100, 50, 30],
            spreads=[0.10, 0.15, 0.20],
            resolution_days=90,
        )
        score = compute_event_quality_score(ev, mkts)
        assert score.total < 50


class TestInformationValue:
    def test_balanced_outcomes_score_higher(self):
        """Event with balanced outcomes (high entropy) scores higher on info value."""
        ev = make_event(event_id="ev1", volume=100000)
        balanced = _make_markets(yes_prices=[0.33, 0.34, 0.33])
        concentrated = _make_markets(yes_prices=[0.90, 0.05, 0.05])

        s_balanced = compute_event_quality_score(ev, balanced)
        s_concentrated = compute_event_quality_score(ev, concentrated)
        assert s_balanced.information_value > s_concentrated.information_value


class TestLiquidityAggregate:
    def test_deep_markets_score_higher(self):
        ev = make_event(event_id="ev1", volume=100000)
        deep = _make_markets(bid_depths=[50000, 40000, 30000])
        thin = _make_markets(bid_depths=[200, 100, 50])

        s_deep = compute_event_quality_score(ev, deep)
        s_thin = compute_event_quality_score(ev, thin)
        assert s_deep.liquidity_aggregate > s_thin.liquidity_aggregate

    def test_high_volume_scores_higher(self):
        ev_high = make_event(event_id="ev1", volume=1000000)
        ev_low = make_event(event_id="ev2", volume=6000)
        mkts = _make_markets()

        s_high = compute_event_quality_score(ev_high, mkts)
        s_low = compute_event_quality_score(ev_low, mkts)
        assert s_high.liquidity_aggregate > s_low.liquidity_aggregate


class TestTimeWindow:
    def test_sweet_spot_scores_highest(self):
        """Events 3-14 days out should score highest on time window."""
        ev = make_event(event_id="ev1", volume=100000)
        sweet = _make_markets(resolution_days=7)
        too_close = _make_markets(resolution_days=0.5)
        too_far = _make_markets(resolution_days=120)

        s_sweet = compute_event_quality_score(ev, sweet)
        s_close = compute_event_quality_score(ev, too_close)
        s_far = compute_event_quality_score(ev, too_far)
        assert s_sweet.time_window >= s_close.time_window
        assert s_sweet.time_window >= s_far.time_window


class TestConsistency:
    def test_fair_overround_scores_higher(self):
        """Low overround (sum ≈ 1.0) is better."""
        ev = make_event(event_id="ev1", volume=100000)
        fair = _make_markets(yes_prices=[0.50, 0.30, 0.20])  # sum=1.0
        inflated = _make_markets(yes_prices=[0.60, 0.40, 0.30])  # sum=1.3

        s_fair = compute_event_quality_score(ev, fair)
        s_inflated = compute_event_quality_score(ev, inflated)
        assert s_fair.consistency >= s_inflated.consistency
