"""Tests for poll_job registration and execution.

TODO: v0.5.0 — rewrite when poll_job is rebuilt for event-first schema.
Many tests were removed because they depended on market_states (deleted).
"""

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.daemon.poll_job import (
    get_poll_interval,
    register_poll_job,
    remove_poll_job,
    restore_poll_jobs_from_db,
)


def test_get_poll_interval():
    config = ScannerConfig()
    assert get_poll_interval("crypto", config.movement) == 10
    assert get_poll_interval("political", config.movement) == 60
    assert get_poll_interval("unknown", config.movement) == 30  # default


def test_register_and_remove_poll_job(tmp_path):
    """Test that job registration returns job metadata."""
    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")

    job_info = register_poll_job(
        market_id="m1",
        market_type="crypto",
        token_id="tok_1",
        config=config,
        db=db,
    )
    assert job_info["market_id"] == "m1"
    assert job_info["interval_seconds"] == 10
    assert job_info["job_id"] == "poll_m1"

    removed = remove_poll_job("m1")
    assert removed is True
    db.close()


def test_restore_poll_jobs_from_db_returns_zero_when_stubbed(tmp_path):
    """restore_poll_jobs_from_db is currently stubbed — returns 0."""
    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")
    count = restore_poll_jobs_from_db(config, db)
    assert count == 0
    db.close()
