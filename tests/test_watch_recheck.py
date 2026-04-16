"""Tests for recheck_event — event-level analysis trigger."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, get_event, upsert_event, upsert_market
from scanner.core.monitor_store import get_event_monitor, upsert_event_monitor
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

    def test_close_disables_monitor(self, db):
        """Closing an event should set auto_monitor=False."""
        upsert_event(EventRow(
            event_id="ev1", title="Test", end_date="2020-01-01T00:00:00Z", updated_at="now",
        ), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        recheck_event("ev1", db=db, service=None, trigger_source="scheduled")

        mon = get_event_monitor("ev1", db)
        assert mon["auto_monitor"] == 0


class TestRecheckWithAI:
    def test_ai_analysis_updates_next_check_at(self, db):
        """When service is provided, AI analysis runs and next_check_at is updated."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q", updated_at="now",
        ), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        mock_version = MagicMock()
        mock_version.narrative_output = {
            "next_check_at": "2027-06-01T09:00:00+08:00",
            "next_check_reason": "FOMC meeting",
        }

        mock_service = MagicMock()
        mock_service.analyze_event = AsyncMock(return_value=mock_version)

        result = recheck_event("ev1", db=db, service=mock_service, trigger_source="movement")

        mock_service.analyze_event.assert_called_once()
        assert result.next_check_at == "2027-06-01T09:00:00+08:00"
        assert result.trigger_source == "movement"

        mon = get_event_monitor("ev1", db)
        assert mon["next_check_at"] == "2027-06-01T09:00:00+08:00"
        assert mon["next_check_reason"] == "FOMC meeting"

    def test_ai_no_next_check_at(self, db):
        """When AI output has no next_check_at, result.next_check_at is None."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q", updated_at="now",
        ), db)

        mock_version = MagicMock()
        mock_version.narrative_output = {"summary": "PASS, no edge."}

        mock_service = MagicMock()
        mock_service.analyze_event = AsyncMock(return_value=mock_version)

        result = recheck_event("ev1", db=db, service=mock_service, trigger_source="scheduled")

        assert result.next_check_at is None

    def test_ai_failure_does_not_crash(self, db):
        """If AI analysis raises, recheck should catch and continue."""
        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q", updated_at="now",
        ), db)

        mock_service = MagicMock()
        mock_service.analyze_event = AsyncMock(side_effect=RuntimeError("agent crashed"))

        result = recheck_event("ev1", db=db, service=mock_service, trigger_source="movement")

        assert result.closed is False
        assert result.next_check_at is None  # failure should not set schedule
        assert result.trigger_source == "movement"
