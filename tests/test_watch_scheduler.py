"""Tests for daemon scheduler — dual executor architecture."""

from unittest.mock import patch

import pytest

from scanner.core.db import PolilyDB
from scanner.daemon.scheduler import WatchScheduler


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


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
