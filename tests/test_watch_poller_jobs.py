from unittest.mock import AsyncMock, MagicMock, patch

from scanner.config import ScannerConfig
from scanner.db import PolilyDB
from scanner.market_state import MarketState, set_market_state
from scanner.movement import MovementResult
from scanner.watch_poller_jobs import (
    _execute_poll,
    get_poll_interval,
    init_poller,
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


def test_restore_poll_jobs_from_db(tmp_path):
    """Restore should register a job for each auto_monitor WATCH market."""
    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")

    # Seed two WATCH markets, one with auto_monitor
    set_market_state("m1", MarketState(
        status="watch", updated_at="2026-04-01T00:00:00",
        title="BTC above $100K?", auto_monitor=True,
        market_type="crypto", clob_token_id_yes="tok_1",
    ), db)
    set_market_state("m2", MarketState(
        status="watch", updated_at="2026-04-01T00:00:00",
        title="Some market", auto_monitor=False,
    ), db)

    count = restore_poll_jobs_from_db(config, db)
    assert count == 1  # only m1 has auto_monitor
    db.close()


def test_execute_poll_triggers_recheck(tmp_path):
    """High magnitude + quality should trigger recheck_market."""
    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")

    # Set up WATCH market state
    set_market_state("m1", MarketState(
        status="watch", updated_at="2026-04-01T00:00:00",
        title="Test Market", auto_monitor=True, price_at_watch=0.40,
    ), db)

    mock_service = MagicMock()
    init_poller(scheduler=None, config=config, db=db, service=mock_service)

    # Mock poll_single to return high-trigger result
    high_result = MovementResult(magnitude=85.0, quality=75.0)

    with patch("scanner.price_poller.PricePoller") as MockPoller, \
         patch("scanner.watch_recheck.recheck_market") as mock_recheck, \
         patch("scanner.notifications.add_notification"), \
         patch("scanner.notifications.send_desktop_notification"):

        mock_poller_instance = MagicMock()
        mock_poller_instance.poll_single = AsyncMock(return_value=high_result)
        mock_poller_instance.check_cooldown.return_value = False
        mock_poller_instance.check_daily_limit.return_value = False
        mock_poller_instance.close = AsyncMock()
        MockPoller.return_value = mock_poller_instance

        _execute_poll("m1", "crypto", "tok_1", "Test Market")

        mock_recheck.assert_called_once()

    # Reset global
    init_poller(scheduler=None, config=None, db=None, service=None)
    db.close()


def test_execute_poll_cooldown_prevents_trigger(tmp_path):
    """Market in cooldown should NOT trigger recheck."""
    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")

    set_market_state("m1", MarketState(
        status="watch", updated_at="2026-04-01T00:00:00",
        title="Test Market", auto_monitor=True, price_at_watch=0.40,
    ), db)

    mock_service = MagicMock()
    init_poller(scheduler=None, config=config, db=db, service=mock_service)

    high_result = MovementResult(magnitude=85.0, quality=75.0)

    with patch("scanner.price_poller.PricePoller") as MockPoller, \
         patch("scanner.watch_recheck.recheck_market") as mock_recheck:

        mock_poller_instance = MagicMock()
        mock_poller_instance.poll_single = AsyncMock(return_value=high_result)
        mock_poller_instance.check_cooldown.return_value = True  # in cooldown
        mock_poller_instance.close = AsyncMock()
        MockPoller.return_value = mock_poller_instance

        _execute_poll("m1", "crypto", "tok_1", "Test Market")

        mock_recheck.assert_not_called()

    init_poller(scheduler=None, config=None, db=None, service=None)
    db.close()


def test_execute_poll_closes_expired_market(tmp_path):
    """Expired market should be closed and poll job removed."""
    from datetime import UTC, datetime, timedelta

    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")

    # Set up market with resolution_time in the past
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    set_market_state("m1", MarketState(
        status="watch", updated_at="2026-04-01T00:00:00",
        title="Expired Market", auto_monitor=True,
        resolution_time=past,
    ), db)

    mock_service = MagicMock()
    init_poller(scheduler=None, config=config, db=db, service=mock_service)

    with patch("scanner.price_poller.PricePoller") as MockPoller:
        _execute_poll("m1", "other", "tok_1", "Expired Market")
        MockPoller.assert_not_called()  # should exit before creating poller

    # Verify market was closed
    from scanner.market_state import get_market_state
    state = get_market_state("m1", db)
    assert state.status == "closed"
    assert state.auto_monitor is True  # kept True — user sees [已结算] in monitor list

    init_poller(scheduler=None, config=None, db=None, service=None)
    db.close()


def test_execute_poll_removes_job_if_not_watch(tmp_path):
    """If market is no longer WATCH, poll job should be removed."""
    config = ScannerConfig()
    db = PolilyDB(tmp_path / "test.db")

    set_market_state("m1", MarketState(
        status="pass", updated_at="2026-04-01T00:00:00",
        title="Passed Market",
    ), db)

    mock_service = MagicMock()
    init_poller(scheduler=None, config=config, db=db, service=mock_service)

    with patch("scanner.price_poller.PricePoller") as MockPoller:
        _execute_poll("m1", "crypto", "tok_1", "Passed Market")
        MockPoller.assert_not_called()  # should exit before creating poller

    init_poller(scheduler=None, config=None, db=None, service=None)
    db.close()
