from unittest.mock import patch

from scanner.auto_monitor import toggle_auto_monitor
from scanner.config import ScannerConfig
from scanner.db import PolilyDB
from scanner.market_state import MarketState, get_market_state, set_market_state


def test_enable_registers_poll_job(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    state = MarketState(
        status="watch",
        updated_at="2026-04-01T00:00:00",
        title="BTC above $100K?",
        auto_monitor=False,
        next_check_at="2026-04-02T00:00:00",
        market_type="crypto",
        clob_token_id_yes="tok_1",
    )
    set_market_state("m1", state, db)

    with patch("scanner.auto_monitor.register_poll_job") as mock_register, \
         patch("scanner.auto_monitor.remove_poll_job") as mock_remove:
        mock_register.return_value = {"job_id": "poll_m1", "interval_seconds": 10,
                                       "market_id": "m1", "market_type": "crypto"}
        toggle_auto_monitor("m1", enable=True, db=db, config=config)

        mock_register.assert_called_once()
        mock_remove.assert_not_called()

    # Verify state was updated
    updated = get_market_state("m1", db)
    assert updated.auto_monitor is True
    db.close()


def test_disable_removes_poll_job(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    state = MarketState(
        status="watch",
        updated_at="2026-04-01T00:00:00",
        title="BTC above $100K?",
        auto_monitor=True,
        market_type="crypto",
        clob_token_id_yes="tok_1",
    )
    set_market_state("m1", state, db)

    with patch("scanner.auto_monitor.register_poll_job") as mock_register, \
         patch("scanner.auto_monitor.remove_poll_job") as mock_remove:
        mock_remove.return_value = True
        toggle_auto_monitor("m1", enable=False, db=db, config=config)

        mock_remove.assert_called_once_with("m1")
        mock_register.assert_not_called()

    updated = get_market_state("m1", db)
    assert updated.auto_monitor is False
    db.close()


def test_enable_on_buy_yes_works(tmp_path):
    """auto_monitor should work on buy_yes status."""
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    state = MarketState(
        status="buy_yes",
        updated_at="2026-04-01T00:00:00",
        title="BTC above $100K?",
        auto_monitor=False,
        market_type="crypto",
        clob_token_id_yes="tok_1",
    )
    set_market_state("m1", state, db)

    with patch("scanner.auto_monitor.register_poll_job") as mock_register:
        mock_register.return_value = {"job_id": "poll_m1", "interval_seconds": 10,
                                       "market_id": "m1", "market_type": "crypto"}
        toggle_auto_monitor("m1", enable=True, db=db, config=config)
        mock_register.assert_called_once()

    updated = get_market_state("m1", db)
    assert updated.auto_monitor is True
    db.close()


def test_enable_on_pass_rejected(tmp_path):
    """auto_monitor should be rejected for pass status."""
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    state = MarketState(
        status="pass",
        updated_at="2026-04-01T00:00:00",
        title="Some market",
    )
    set_market_state("m1", state, db)

    with patch("scanner.auto_monitor.register_poll_job") as mock_register:
        toggle_auto_monitor("m1", enable=True, db=db, config=config)
        mock_register.assert_not_called()
    db.close()


def test_enable_on_closed_rejected(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    config = ScannerConfig()

    state = MarketState(
        status="closed",
        updated_at="2026-04-01T00:00:00",
        title="Closed market",
    )
    set_market_state("m1", state, db)

    with patch("scanner.auto_monitor.register_poll_job") as mock_register:
        toggle_auto_monitor("m1", enable=True, db=db, config=config)
        mock_register.assert_not_called()
    db.close()
