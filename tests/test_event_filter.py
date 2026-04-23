"""Tests for event-level filtering."""

from datetime import UTC, datetime, timedelta

from polily.scan.filters import filter_events
from tests.conftest import make_event, make_market


def _make_event_with_markets(event_id="ev1", title="Test Event", volume=50000,
                              end_date=None, markets=None, **event_kw):
    """Helper: build (EventRow, list[Market]) tuple."""
    if end_date is None:
        end_date = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    ev = make_event(event_id=event_id, title=title, volume=volume,
                    end_date=end_date, **event_kw)
    if markets is None:
        markets = [make_market(market_id=f"{event_id}_m1", event_id=event_id,
                              yes_price=0.55, volume=30000)]
    return ev, markets


class TestEventFilterVolume:
    def test_good_volume_passes(self):
        ev, mkts = _make_event_with_markets(volume=50000)
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids

    def test_low_volume_rejected(self):
        ev, mkts = _make_event_with_markets(volume=100)
        result = filter_events([(ev, mkts)])
        assert ev.event_id not in result.passed_event_ids

    def test_volume_none_passes(self):
        """Event with volume=None should pass (unknown, not rejected)."""
        ev, mkts = _make_event_with_markets(volume=None)
        ev.volume = None
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids


class TestEventFilterExpiry:
    def test_future_end_date_passes(self):
        end = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        ev, mkts = _make_event_with_markets(end_date=end)
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids

    def test_past_end_date_rejected(self):
        end = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        ev, mkts = _make_event_with_markets(end_date=end)
        result = filter_events([(ev, mkts)])
        assert ev.event_id not in result.passed_event_ids

    def test_no_end_date_still_passes(self):
        """Events without end_date should not be rejected (some events are open-ended)."""
        ev, mkts = _make_event_with_markets(end_date=None)
        ev.end_date = None
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids


class TestEventFilterActiveMarkets:
    def test_has_active_market_passes(self):
        ev, mkts = _make_event_with_markets()
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids

    def test_no_markets_rejected(self):
        ev, _ = _make_event_with_markets()
        result = filter_events([(ev, [])])
        assert ev.event_id not in result.passed_event_ids

    def test_all_zero_price_rejected(self):
        """Event where all sub-markets have price 0 or None is rejected."""
        mkts = [
            make_market(market_id="m1", event_id="ev1", yes_price=0.0),
            make_market(market_id="m2", event_id="ev1", yes_price=None),
        ]
        ev, _ = _make_event_with_markets(markets=mkts)
        result = filter_events([(ev, mkts)])
        assert ev.event_id not in result.passed_event_ids


class TestEventFilterNoise:
    def test_noise_title_rejected(self):
        ev, mkts = _make_event_with_markets(title="BTC 5 min up or down?")
        result = filter_events([(ev, mkts)])
        assert ev.event_id not in result.passed_event_ids

    def test_normal_title_passes(self):
        ev, mkts = _make_event_with_markets(title="Will BTC be above $88,000?")
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids


class TestEventFilterAllSubMarketsScored:
    def test_all_sub_markets_in_passed(self):
        """When event passes, ALL sub-markets are in the result — not just 'good' ones."""
        mkts = [
            make_market(market_id="m1", event_id="ev1", yes_price=0.55, volume=50000),
            make_market(market_id="m2", event_id="ev1", yes_price=0.02, volume=50000),  # extreme price
            make_market(market_id="m3", event_id="ev1", yes_price=0.98, volume=50000),  # extreme price
        ]
        ev, _ = _make_event_with_markets(markets=mkts)
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids
        # ALL 3 markets should be in passed_markets, not just m1
        passed_mids = {m.market_id for m in result.passed_markets}
        assert "m1" in passed_mids
        assert "m2" in passed_mids
        assert "m3" in passed_mids


class TestEventFilterTimeWindow:
    def test_over_60_days_rejected(self):
        """Events with nearest resolution > 60 days should be rejected."""
        end = (datetime.now(UTC) + timedelta(days=90)).isoformat()
        mkts = [make_market(market_id="m1", event_id="ev1", yes_price=0.55,
                           resolution_time=datetime.now(UTC) + timedelta(days=90))]
        ev, _ = _make_event_with_markets(end_date=end, markets=mkts)
        result = filter_events([(ev, mkts)])
        assert ev.event_id not in result.passed_event_ids

    def test_under_60_days_passes(self):
        end = (datetime.now(UTC) + timedelta(days=30)).isoformat()
        mkts = [make_market(market_id="m1", event_id="ev1", yes_price=0.55,
                           resolution_time=datetime.now(UTC) + timedelta(days=30))]
        ev, _ = _make_event_with_markets(end_date=end, markets=mkts)
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids

    def test_over_30_days_all_extreme_rejected(self):
        """> 30 days + all sub-markets extreme probability → rejected."""
        end = (datetime.now(UTC) + timedelta(days=45)).isoformat()
        mkts = [
            make_market(market_id="m1", event_id="ev1", yes_price=0.95,
                       resolution_time=datetime.now(UTC) + timedelta(days=45)),
            make_market(market_id="m2", event_id="ev1", yes_price=0.03,
                       resolution_time=datetime.now(UTC) + timedelta(days=45)),
        ]
        ev, _ = _make_event_with_markets(end_date=end, markets=mkts)
        result = filter_events([(ev, mkts)])
        assert ev.event_id not in result.passed_event_ids

    def test_over_30_days_balanced_passes(self):
        """> 30 days but balanced probability → passes."""
        end = (datetime.now(UTC) + timedelta(days=45)).isoformat()
        mkts = [
            make_market(market_id="m1", event_id="ev1", yes_price=0.55,
                       resolution_time=datetime.now(UTC) + timedelta(days=45)),
            make_market(market_id="m2", event_id="ev1", yes_price=0.45,
                       resolution_time=datetime.now(UTC) + timedelta(days=45)),
        ]
        ev, _ = _make_event_with_markets(end_date=end, markets=mkts)
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids


class TestEventFilterVolumeNone:
    def test_volume_none_passes(self):
        """Event with volume=None should pass (unknown, not rejected)."""
        ev, mkts = _make_event_with_markets(volume=None)
        ev.volume = None
        result = filter_events([(ev, mkts)])
        assert ev.event_id in result.passed_event_ids


class TestEventFilterResult:
    def test_result_counts(self):
        events = [
            _make_event_with_markets(event_id="ev1", volume=50000),
            _make_event_with_markets(event_id="ev2", volume=100),  # low volume
            _make_event_with_markets(event_id="ev3", volume=80000),
        ]
        result = filter_events(events)
        assert len(result.passed_event_ids) == 2
        assert len(result.rejected) >= 1
