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
        assert m.event_id is None
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

    def test_round_trip_friction_pct(self):
        m = make_market(best_bid_yes=0.54, best_ask_yes=0.56)
        # Estimated as 2 * spread_pct (buy in + sell out)
        assert m.round_trip_friction_pct is not None
        assert m.round_trip_friction_pct > 0.05  # ~7.3% for this spread

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
