"""Tests for market data models."""

from datetime import UTC, datetime

from scanner.core.models import BookLevel, Market
from tests.conftest import make_market


class TestBookLevel:
    def test_create_book_level(self):
        level = BookLevel(price=0.55, size=1200.0)
        assert level.price == 0.55
        assert level.size == 1200.0


class TestMarket:

    def test_create_minimal_market(self):
        m = make_market(market_id="0xabc123")
        assert m.market_id == "0xabc123"
        assert m.yes_price == 0.55

    def test_optional_fields_default_none(self):
        m = make_market()
        assert m.event_id == "ev_test"
        assert m.description is None
        assert m.rules is None
        assert m.category is None
        assert m.resolution_source is None
        assert m.market_type is None

    def test_tags_default_empty(self):
        m = make_market()
        assert m.tags == []

    def test_mid_price_yes(self):
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)
        assert m.mid_price_yes == 0.55

    def test_mid_price_yes_missing_bid(self):
        m = make_market(best_bid_yes=None, best_ask_yes=0.56)
        assert m.mid_price_yes is None

    def test_spread_pct_yes(self):
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)
        # spread_pct = spread / mid = 0.02 / 0.55 ≈ 0.03636
        assert m.spread_pct_yes is not None
        assert abs(m.spread_pct_yes - 0.03636) < 0.001

    def test_days_to_resolution(self):
        m = make_market(
            resolution_time=datetime(2026, 3, 30, 0, 0, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
        )
        assert m.days_to_resolution is not None
        assert abs(m.days_to_resolution - 2.0) < 0.01

    def test_days_to_resolution_none_when_no_resolution_time(self):
        m = make_market(resolution_time=None)
        assert m.days_to_resolution is None

    def test_hours_to_resolution(self):
        m = make_market(
            resolution_time=datetime(2026, 3, 30, 0, 0, tzinfo=UTC),
            data_fetched_at=datetime(2026, 3, 28, 0, 0, tzinfo=UTC),
        )
        assert m.hours_to_resolution is not None
        assert abs(m.hours_to_resolution - 48.0) < 0.1

    def test_is_binary_market_true(self):
        m = make_market(outcomes=["Yes", "No"])
        assert m.is_binary is True

    def test_is_binary_market_false(self):
        m = make_market(outcomes=["Trump", "Biden", "DeSantis"])
        assert m.is_binary is False

    def test_is_extreme_probability(self):
        assert make_market(yes_price=0.05).is_extreme_probability is True
        assert make_market(yes_price=0.95).is_extreme_probability is True
        assert make_market(yes_price=0.50).is_extreme_probability is False

    def test_is_mid_probability(self):
        assert make_market(yes_price=0.50).is_mid_probability is True
        assert make_market(yes_price=0.35).is_mid_probability is True
        assert make_market(yes_price=0.10).is_mid_probability is False
        assert make_market(yes_price=0.90).is_mid_probability is False

    def test_round_trip_friction_pct_symmetric(self):
        """Near 50¢ YES — both sides have similar % cost; YES used."""
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)
        # spread_abs=0.02, mid_yes=0.55, mid_no=0.45
        # spread_pct_yes = 0.02/0.55 ≈ 0.0364 (cheaper)
        # spread_pct_no  = 0.02/0.45 ≈ 0.0444
        # best-side round-trip = 2 × 0.0364 ≈ 0.0727
        assert m.round_trip_friction_pct is not None
        assert abs(m.round_trip_friction_pct - 0.0727) < 0.002

    def test_round_trip_friction_pct_low_yes_uses_no_side(self):
        """Low YES (like Iran peace deal at 25¢): buying NO is way cheaper
        than buying YES because NO's 75¢ mid dilutes the same absolute spread.
        Bug this test locks in: old formula used YES-side only and flagged
        everything below 0.5 as high-friction.
        """
        # Matches the Iran April 22 market: YES=0.24/0.25, NO=0.75/0.76, spread=0.01.
        m = make_market(best_bid_yes=0.24, best_ask_yes=0.25)
        # spread_abs=0.01, mid_yes=0.245, mid_no=0.755
        # spread_pct_yes = 0.01/0.245 = 4.08% (worse)
        # spread_pct_no  = 0.01/0.755 = 1.32% (better — the actionable side)
        # round-trip = 2 × 1.32% = 2.65%
        assert m.round_trip_friction_pct is not None
        assert abs(m.round_trip_friction_pct - 0.0265) < 0.002
        # Without the fix it would be ~0.0816.

    def test_round_trip_friction_pct_high_yes_uses_yes_side(self):
        """High YES (favorite at 75¢): buying YES is the cheaper side.
        Mirrors the low-YES case by symmetry.
        """
        m = make_market(best_bid_yes=0.75, best_ask_yes=0.76)
        # mid_yes=0.755, mid_no=0.245, spread=0.01
        # spread_pct_yes = 1.32%; spread_pct_no = 4.08%; min=1.32%; round-trip=2.65%
        assert m.round_trip_friction_pct is not None
        assert abs(m.round_trip_friction_pct - 0.0265) < 0.002

    def test_round_trip_friction_pct_exact_half(self):
        """YES = 0.5 boundary — both sides identical by construction."""
        m = make_market(best_bid_yes=0.495, best_ask_yes=0.505)
        # mid=0.5, spread_abs=0.01, spread_pct_yes = spread_pct_no = 2%
        # round-trip = 4%
        assert m.round_trip_friction_pct is not None
        assert abs(m.round_trip_friction_pct - 0.04) < 0.001

    def test_round_trip_friction_pct_extreme_price_still_finite(self):
        """At 1¢ YES, YES side is effectively untradeable (100% spread %),
        but NO side at 99¢ has a sane spread %. Best-side keeps us honest.
        """
        m = make_market(best_bid_yes=0.005, best_ask_yes=0.015)
        # spread_abs=0.01, mid_yes=0.01 → YES spread_pct = 100% (useless)
        # mid_no=0.99 → NO spread_pct = 1.01% → round-trip ≈ 2.02%
        assert m.round_trip_friction_pct is not None
        assert m.round_trip_friction_pct < 0.03

    def test_book_depth_totals(self):
        bids = [BookLevel(price=0.54, size=500), BookLevel(price=0.53, size=800)]
        asks = [BookLevel(price=0.56, size=400), BookLevel(price=0.57, size=600)]
        m = make_market(book_depth_bids=bids, book_depth_asks=asks)
        assert m.total_bid_depth_usd == 1300.0
        assert m.total_ask_depth_usd == 1000.0

    def test_book_depth_none_when_no_book(self):
        m = make_market(book_depth_bids=None, book_depth_asks=None)
        assert m.total_bid_depth_usd is None
        assert m.total_ask_depth_usd is None

    def test_serialization_roundtrip(self):
        m = make_market()
        json_str = m.model_dump_json()
        m2 = Market.model_validate_json(json_str)
        assert m2.market_id == m.market_id
        assert m2.yes_price == m.yes_price

    def test_json_schema_generation(self):
        schema = Market.model_json_schema()
        assert "properties" in schema
        assert "market_id" in schema["properties"]

    def test_polymarket_url_with_slugs(self):
        m = make_market(event_slug="btc-above-88k-123", market_slug="will-btc-be-above-88k-456")
        assert m.polymarket_url == "https://polymarket.com/event/btc-above-88k-123/will-btc-be-above-88k-456"

    def test_polymarket_url_event_slug_only(self):
        m = make_market(event_slug="btc-above-88k-123", market_slug=None)
        assert m.polymarket_url == "https://polymarket.com/event/btc-above-88k-123"

    def test_polymarket_url_no_slug_fallback(self):
        m = make_market(market_id="1515775", event_slug=None, market_slug=None)
        assert m.polymarket_url == "https://polymarket.com/event/1515775"


class TestNewComputedFields:
    def test_vamp_balanced_book(self):
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56,
                       book_depth_bids=[BookLevel(price=0.54, size=1000)],
                       book_depth_asks=[BookLevel(price=0.56, size=1000)])
        assert m.vamp is not None
        assert abs(m.vamp - 0.55) < 0.01  # balanced -> same as mid

    def test_vamp_imbalanced_book(self):
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56,
                       book_depth_bids=[BookLevel(price=0.54, size=100)],
                       book_depth_asks=[BookLevel(price=0.56, size=900)])
        # VAMP = (bid*ask_depth + ask*bid_depth) / total_depth
        # More ask depth -> more weight on bid price -> VAMP < mid
        assert m.vamp < 0.55

    def test_obi_balanced(self):
        m = make_market(book_depth_bids=[BookLevel(price=0.5, size=1000)],
                       book_depth_asks=[BookLevel(price=0.6, size=1000)])
        assert m.order_book_imbalance == 0.0

    def test_obi_bid_heavy(self):
        m = make_market(book_depth_bids=[BookLevel(price=0.5, size=900)],
                       book_depth_asks=[BookLevel(price=0.6, size=100)])
        assert m.order_book_imbalance > 0.5

    def test_obi_none_when_no_depth(self):
        m = make_market(book_depth_bids=None, book_depth_asks=None)
        assert m.order_book_imbalance is None

    def test_slippage_20usd(self):
        m = make_market(book_depth_bids=[BookLevel(price=0.5, size=10000)])
        assert m.slippage_20usd is not None
        assert abs(m.slippage_20usd - 0.001) < 0.001  # 20/(2*10000) = 0.001

    def test_slippage_none_when_no_depth(self):
        m = make_market(book_depth_bids=None)
        assert m.slippage_20usd is None
