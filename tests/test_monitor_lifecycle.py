"""Integration tests for decoupled monitoring lifecycle."""

import os
from unittest.mock import patch

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.daemon.auto_monitor import toggle_auto_monitor
from scanner.market_state import (
    MarketState,
    get_active_monitors,
    get_auto_monitor_watches,
    get_market_state,
    set_market_state,
)


def test_monitor_independent_of_status(tmp_path):
    """auto_monitor works for watch, buy_yes, buy_no."""
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    for status in ("watch", "buy_yes", "buy_no"):
        set_market_state(f"m_{status}", MarketState(
            status=status, updated_at="2026-04-01T00:00:00",
            title=f"Test {status}",
        ), db)

        with patch("scanner.daemon.auto_monitor.register_poll_job") as mock_reg:
            mock_reg.return_value = {"job_id": f"poll_m_{status}", "interval_seconds": 30,
                                     "market_id": f"m_{status}", "market_type": "other"}
            toggle_auto_monitor(f"m_{status}", enable=True, db=db, config=config)
            mock_reg.assert_called_once()

        state = get_market_state(f"m_{status}", db)
        assert state.auto_monitor is True
    db.close()


def test_pass_disables_monitor(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    set_market_state("m1", MarketState(
        status="watch", updated_at="2026-04-01T00:00:00",
        title="Test", auto_monitor=True,
    ), db)

    with patch("scanner.daemon.auto_monitor.remove_poll_job"):
        toggle_auto_monitor("m1", enable=False, db=db, config=config)

    state = get_market_state("m1", db)
    assert state.auto_monitor is False
    db.close()


def test_monitor_list_shows_mixed_statuses(tmp_path):
    """Monitor list includes markets of any status with auto_monitor=1."""
    db = PolilyDB(tmp_path / "test.db")
    set_market_state("m_watch", MarketState(
        status="watch", updated_at="2026-04-01", title="Watch", auto_monitor=True), db)
    set_market_state("m_buy", MarketState(
        status="buy_yes", updated_at="2026-04-01", title="Buy", auto_monitor=True), db)
    set_market_state("m_pass", MarketState(
        status="pass", updated_at="2026-04-01", title="Pass", auto_monitor=False), db)

    monitors = get_auto_monitor_watches(db)
    assert len(monitors) == 2
    assert "m_watch" in monitors
    assert "m_buy" in monitors
    assert "m_pass" not in monitors
    db.close()


def test_notify_daemon_sends_sigusr1(tmp_path):
    """notify_daemon should send SIGUSR1 to PID in file."""
    import signal

    from scanner.daemon.notify import notify_daemon

    pid_path = tmp_path / "scheduler.pid"
    pid_path.write_text(str(os.getpid()))

    with patch("scanner.daemon.notify.PID_PATH", pid_path), \
         patch("os.kill") as mock_kill:
        result = notify_daemon()
        assert result is True
        mock_kill.assert_called_once_with(os.getpid(), signal.SIGUSR1)


def test_notify_daemon_no_pid_file():
    from pathlib import Path

    from scanner.daemon.notify import notify_daemon

    with patch("scanner.daemon.notify.PID_PATH", Path("/nonexistent/path")):
        result = notify_daemon()
        assert result is False


def test_notify_daemon_stale_pid(tmp_path):
    """Stale PID (process doesn't exist) should return False gracefully."""
    from scanner.daemon.notify import notify_daemon

    pid_path = tmp_path / "scheduler.pid"
    pid_path.write_text("999999999")  # unlikely to exist

    with patch("scanner.daemon.notify.PID_PATH", pid_path):
        result = notify_daemon()
        assert result is False


def test_closed_market_stays_in_monitor_list(tmp_path):
    """Closed markets should remain in monitor list (display) but not in active monitors (polling)."""
    db = PolilyDB(tmp_path / "test.db")

    # Market was being monitored, then got closed (expired)
    set_market_state("m1", MarketState(
        status="closed", updated_at="2026-04-07", title="Expired BTC market", auto_monitor=True,
    ), db)

    # Should appear in display list
    display = get_auto_monitor_watches(db)
    assert "m1" in display

    # Should NOT appear in polling list
    active = get_active_monitors(db)
    assert "m1" not in active
    db.close()
