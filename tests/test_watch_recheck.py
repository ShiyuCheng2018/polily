"""Tests for recheck_event — event-level analysis trigger."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, get_event, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.daemon.recheck import RecheckResult, recheck_event


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


class TestRecheckGateOnAlreadyClosed:
    """Since `auto_monitor` now stays 1 through close (user-intent flag), the
    scheduler may still fire `recheck_event` on an already-closed event. That
    path must no-op — not re-emit a [CLOSED] notification, not mutate any row.
    """

    def test_early_returns_for_already_closed_event(self, db):
        """A closed event must no-op through recheck — Layer 2 would otherwise
        re-enter `_close_event` and the gate on `event.closed == 1` must
        short-circuit before Layer 2 runs."""
        upsert_event(EventRow(
            event_id="ev1", title="Already closed event", closed=1,
            updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q", closed=1,
            updated_at="now",
        ), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        result = recheck_event("ev1", db=db, service=None, trigger_source="scheduled")
        assert result.closed is False


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


class TestRecheckWithAI:
    def test_ai_analysis_updates_next_check_at(self, db):
        """When service is provided, AI analysis runs and a pending scan_logs
        row is inserted for the next check."""
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

        # The new scheduling path writes a pending row to scan_logs rather
        # than mutating event_monitors (which lost next_check_at in v0.7.0).
        pending = db.conn.execute(
            "SELECT scheduled_at, scheduled_reason, trigger_source, status "
            "FROM scan_logs WHERE event_id = ? AND status = 'pending'",
            ("ev1",),
        ).fetchone()
        assert pending is not None
        assert pending["scheduled_at"] == "2027-06-01T09:00:00+08:00"
        assert pending["scheduled_reason"] == "FOMC meeting"
        assert pending["trigger_source"] == "scheduled"

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
