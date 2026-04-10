"""Tests for daemon scheduler — dual executor architecture."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.monitor_store import update_next_check_at, upsert_event_monitor
from scanner.daemon.scheduler import WatchScheduler


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed_event(db, event_id: str):
    """Insert a minimal event row for FK constraints."""
    upsert_event(EventRow(event_id=event_id, title="E", updated_at="now"), db)


class TestSchedulerCreation:
    def test_has_dual_executors(self, db):
        ws = WatchScheduler(db)
        ws.start()
        executors = ws.scheduler._executors
        assert "poll" in executors
        assert "ai" in executors
        ws.shutdown()

    def test_registers_global_poll_job(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            jobs = ws.scheduler.get_jobs()
            poll_jobs = [j for j in jobs if j.id == "global_poll"]
            assert len(poll_jobs) == 1
            ws.shutdown()

    def test_global_poll_uses_poll_executor(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            poll_job = ws.scheduler.get_job("global_poll")
            assert poll_job.executor == "poll"
            ws.shutdown()


class TestCheckJobRestore:
    def test_restores_check_jobs_from_db(self, db):
        _seed_event(db, "ev1")
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        update_next_check_at("ev1", "2026-04-12T14:00:00", "CPI release", db)

        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            count = ws.restore_check_jobs()
            assert count == 1
            jobs = ws.scheduler.get_jobs()
            check_jobs = [j for j in jobs if j.id.startswith("check_")]
            assert len(check_jobs) == 1
            assert check_jobs[0].executor == "ai"
            ws.shutdown()

    def test_skips_events_without_next_check_at(self, db):
        _seed_event(db, "ev1")
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        # No next_check_at set

        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            count = ws.restore_check_jobs()
            assert count == 0
            ws.shutdown()

    def test_overdue_check_jobs_rescheduled_near_future(self, db):
        _seed_event(db, "ev1")
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        update_next_check_at("ev1", past, "overdue", db)

        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            count = ws.restore_check_jobs()
            assert count == 1
            job = ws.scheduler.get_job("check_ev1")
            assert job is not None
            # Should be scheduled in the near future, not in the past
            assert job.next_run_time > datetime.now(UTC) - timedelta(seconds=1)
            ws.shutdown()


class TestScheduleAndCancel:
    def test_schedule_check(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            ws.schedule_check("ev1", datetime.now(UTC) + timedelta(hours=1))
            jobs = [j for j in ws.scheduler.get_jobs() if j.id == "check_ev1"]
            assert len(jobs) == 1
            ws.shutdown()

    def test_cancel_check(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            ws.schedule_check("ev1", datetime.now(UTC) + timedelta(hours=1))
            ws.cancel_check("ev1")
            jobs = [j for j in ws.scheduler.get_jobs() if j.id == "check_ev1"]
            assert len(jobs) == 0
            ws.shutdown()

    def test_cancel_nonexistent_no_error(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            ws.cancel_check("nonexistent")  # should not raise
            ws.shutdown()

    def test_schedule_check_replaces_existing(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            t1 = datetime.now(UTC) + timedelta(hours=1)
            t2 = datetime.now(UTC) + timedelta(hours=2)
            ws.schedule_check("ev1", t1)
            ws.schedule_check("ev1", t2)
            jobs = [j for j in ws.scheduler.get_jobs() if j.id == "check_ev1"]
            assert len(jobs) == 1
            ws.shutdown()

    def test_list_pending_jobs(self, db):
        with patch("scanner.daemon.scheduler.global_poll"):
            ws = WatchScheduler(db)
            ws.start()
            ws.schedule_check("ev1", datetime.now(UTC) + timedelta(hours=1))
            ws.schedule_check("ev2", datetime.now(UTC) + timedelta(hours=2))
            pending = ws.list_pending()
            # global_poll + 2 check jobs
            assert len(pending) == 3
            ws.shutdown()


class TestExecuteCheck:
    def test_execute_check_calls_recheck(self, db):
        """_execute_check should call recheck_event with correct args."""
        from scanner.daemon.scheduler import _execute_check

        upsert_event(EventRow(event_id="ev1", title="E", updated_at="now"), db)

        with patch("scanner.daemon.recheck.recheck_event") as mock_recheck:
            mock_recheck.return_value = MagicMock(closed=False, next_check_at=None)
            _execute_check(event_id="ev1", db=db, config=None, watch_scheduler=None)

        mock_recheck.assert_called_once_with("ev1", db=db, trigger_source="scheduled")
