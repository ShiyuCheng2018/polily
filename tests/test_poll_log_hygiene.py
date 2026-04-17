"""Regression guard for test-run pollution of data/poll.log.

`scanner.daemon.poll_job._get_poll_log()` is a module-level singleton
hard-coded to write `<project_root>/data/poll.log`. Without isolation,
every integration test that calls `global_poll()` or
`_resolve_closed_market_if_position()` appends to the developer's live
poll log, making post-run diagnostics messy.

These tests assert the `_isolate_poll_log` autouse fixture (in
conftest.py) renders `_get_poll_log()` a silent no-op during tests.
"""

from pathlib import Path
from unittest.mock import MagicMock

from scanner.daemon import poll_job

PROD_LOG = Path(__file__).resolve().parent.parent / "data" / "poll.log"


def test_get_poll_log_returns_mock_during_tests():
    """Contract: the autouse fixture must redirect to a Mock — never the
    real FileHandler-backed logger."""
    log = poll_job._get_poll_log()
    assert isinstance(log, MagicMock), (
        f"Expected MagicMock from _get_poll_log during tests, got {type(log)}. "
        "The _isolate_poll_log autouse fixture in conftest.py is not active."
    )


def test_emitting_plog_does_not_touch_prod_log_file():
    """Even a direct info() call from a test must not reach disk."""
    size_before = PROD_LOG.stat().st_size if PROD_LOG.exists() else 0
    poll_job._get_poll_log().info("TEST POLLUTION SENTINEL")
    size_after = PROD_LOG.stat().st_size if PROD_LOG.exists() else 0
    assert size_before == size_after, (
        f"plog.info() leaked {size_after - size_before} bytes into prod "
        f"{PROD_LOG}; autouse fixture not suppressing writes."
    )


def test_poll_count_resets_between_tests_part_a():
    """First half of pair: confirm _poll_count starts at 0 for this test."""
    assert poll_job._poll_count == 0, (
        f"_poll_count leaked from prior test: {poll_job._poll_count}. "
        "Autouse fixture must reset module-level state."
    )
    poll_job._poll_count = 99  # simulate mid-tick state


def test_poll_count_resets_between_tests_part_b():
    """Second half: verify reset happened despite prior test setting 99."""
    assert poll_job._poll_count == 0
