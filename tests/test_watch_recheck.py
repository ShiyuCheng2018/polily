"""Tests for recheck_event — event-level analysis trigger."""
import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, get_event, upsert_event, upsert_market
from scanner.daemon.recheck import RecheckResult, recheck_event


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


class TestRecheckExpiry:
    def test_expired_event_gets_closed(self, db):
        """Event past end_date should be closed."""
        upsert_event(EventRow(
            event_id="ev1", title="E", end_date="2020-01-01T00:00:00Z", updated_at="now",
        ), db)
        result = recheck_event("ev1", db=db, service=None, trigger_source="scheduled")
        assert result.closed is True
        event = get_event("ev1", db)
        assert event.closed == 1

    def test_all_sub_markets_closed(self, db):
        """Event where all sub-markets are closed should be closed."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q1", closed=1, updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m2", event_id="ev1", question="Q2", closed=1, updated_at="now",
        ), db)
        result = recheck_event("ev1", db=db, service=None, trigger_source="movement")
        assert result.closed is True
        event = get_event("ev1", db)
        assert event.closed == 1

    def test_partial_close_stays_open(self, db):
        """Event with some closed sub-markets should NOT be closed."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q1", closed=1, updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m2", event_id="ev1", question="Q2", closed=0, updated_at="now",
        ), db)
        result = recheck_event("ev1", db=db, service=None, trigger_source="movement")
        assert result.closed is False
        event = get_event("ev1", db)
        assert event.closed == 0

    def test_no_end_date_stays_open(self, db):
        """Event without end_date should not be closed by expiry check."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q", updated_at="now",
        ), db)
        result = recheck_event("ev1", db=db, service=None, trigger_source="scheduled")
        assert result.closed is False


class TestRecheckWithoutService:
    def test_returns_result_without_service(self, db):
        """When service=None, returns current state without AI analysis."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q", updated_at="now",
        ), db)
        result = recheck_event("ev1", db=db, service=None, trigger_source="manual")
        assert isinstance(result, RecheckResult)
        assert result.event_id == "ev1"
        assert result.closed is False

    def test_nonexistent_event_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            recheck_event("nonexistent", db=db, service=None, trigger_source="manual")


class TestRecheckNotification:
    def test_close_sends_notification(self, db):
        """Closing an event should create a notification."""
        upsert_event(EventRow(
            event_id="ev1", title="Test Market", end_date="2020-01-01T00:00:00Z", updated_at="now",
        ), db)
        recheck_event("ev1", db=db, service=None, trigger_source="scheduled")

        notifs = db.conn.execute("SELECT * FROM notifications").fetchall()
        assert len(notifs) >= 1
        assert "CLOSED" in notifs[0]["title"] or "closed" in notifs[0]["title"].lower()
