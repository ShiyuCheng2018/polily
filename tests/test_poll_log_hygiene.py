"""Regression guard for test-run pollution of prod poll logs.

`polily.daemon.poll_job._get_poll_log()` lazily builds a logger backed
by `<project_root>/data/logs/poll-v<version>-<timestamp>.log`. Without
isolation, every integration test that calls `global_poll()` or
`_resolve_closed_market_if_position()` would create junk log files in
the developer's data/logs directory.

These tests assert the `_isolate_poll_log` autouse fixture (in
conftest.py) renders `_get_poll_log()` a silent no-op during tests.
"""

from pathlib import Path
from unittest.mock import MagicMock

from polily.daemon import poll_job

PROD_LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


def test_get_poll_log_returns_mock_during_tests():
    """Contract: the autouse fixture must redirect to a Mock — never the
    real FileHandler-backed logger."""
    log = poll_job._get_poll_log()
    assert isinstance(log, MagicMock), (
        f"Expected MagicMock from _get_poll_log during tests, got {type(log)}. "
        "The _isolate_poll_log autouse fixture in conftest.py is not active."
    )


def test_emitting_plog_does_not_touch_prod_log_dir():
    """Even a direct info() call from a test must not create files in
    data/logs/ or grow any existing ones.
    """
    # Snapshot prod log dir: names + sizes.
    def _snapshot() -> dict[str, int]:
        if not PROD_LOG_DIR.exists():
            return {}
        return {p.name: p.stat().st_size for p in PROD_LOG_DIR.iterdir() if p.is_file()}

    before = _snapshot()
    poll_job._get_poll_log().info("TEST POLLUTION SENTINEL")
    after = _snapshot()
    assert before == after, (
        f"plog.info() leaked into prod {PROD_LOG_DIR}: before={before}, after={after}; "
        "autouse fixture not suppressing writes."
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
