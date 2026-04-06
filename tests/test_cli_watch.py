"""Tests for WATCH lifecycle CLI commands."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

from scanner.cli import app
from scanner.db import PolilyDB
from scanner.market_state import MarketState, get_market_state, set_market_state

runner = CliRunner()


def _setup_db(tmp: str) -> PolilyDB:
    """Create a temp DB and point config at it."""
    db_path = Path(tmp) / "polily.db"
    return PolilyDB(db_path)


def _make_config_yaml(tmp: str, db_path: str) -> str:
    """Write a minimal config YAML pointing to temp db."""
    config_path = Path(tmp) / "config.yaml"
    config_path.write_text(f"""
archiving:
  db_file: "{db_path}"
  archive_dir: "{tmp}/scans"
""")
    return str(config_path)


class TestWatchList:
    def test_watch_list_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            result = runner.invoke(app, ["watch-list", "--config", config_path])
            assert result.exit_code == 0
            db.close()

    def test_watch_list_shows_markets(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
            set_market_state("0xabc", MarketState(
                status="watch", updated_at=datetime.now(UTC).isoformat(),
                title="BTC 68000", next_check_at=future,
                watch_reason="tariff", watch_sequence=1, auto_monitor=True,
            ), db)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["watch-list", "--config", config_path])
            assert result.exit_code == 0
            assert "BTC 68000" in result.output


class TestPassMarket:
    def test_pass_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            set_market_state("0xabc", MarketState(
                status="watch", updated_at=datetime.now(UTC).isoformat(),
                title="BTC 68000",
            ), db)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["pass-market", "0xabc", "--config", config_path])
            assert result.exit_code == 0
            db2 = PolilyDB(Path(tmp) / "polily.db")
            state = get_market_state("0xabc", db2)
            assert state.status == "pass"
            db2.close()

    def test_pass_nonexistent_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["pass-market", "0xnonexistent", "--config", config_path])
            assert result.exit_code != 0 or "not found" in result.output.lower()


class TestWatchCommand:
    def test_watch_enable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            set_market_state("0xabc", MarketState(
                status="watch", updated_at=datetime.now(UTC).isoformat(),
                title="BTC 68000", auto_monitor=False,
            ), db)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["watch", "0xabc", "--enable", "--config", config_path])
            assert result.exit_code == 0
            db2 = PolilyDB(Path(tmp) / "polily.db")
            state = get_market_state("0xabc", db2)
            assert state.auto_monitor is True
            db2.close()

    def test_watch_disable(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            set_market_state("0xabc", MarketState(
                status="watch", updated_at=datetime.now(UTC).isoformat(),
                title="BTC 68000", auto_monitor=True,
            ), db)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["watch", "0xabc", "--disable", "--config", config_path])
            assert result.exit_code == 0
            db2 = PolilyDB(Path(tmp) / "polily.db")
            state = get_market_state("0xabc", db2)
            assert state.auto_monitor is False
            db2.close()


class TestCheckCommand:
    def test_check_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["check", "0xnonexistent", "--config", config_path])
            assert result.exit_code != 0 or "not found" in result.output.lower()

    def test_check_expired_market(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = _setup_db(tmp)
            set_market_state("0xabc", MarketState(
                status="watch", updated_at=datetime.now(UTC).isoformat(),
                title="Expired Market",
                resolution_time="2020-01-01T00:00:00+00:00",
            ), db)
            config_path = _make_config_yaml(tmp, str(db.db_path))
            db.close()
            result = runner.invoke(app, ["check", "0xabc", "--config", config_path])
            assert result.exit_code == 0
            assert "CLOSED" in result.output or "closed" in result.output
