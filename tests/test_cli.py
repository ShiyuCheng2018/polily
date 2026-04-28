"""Tests for `polily/cli.py` helpers.

T2.4 — verify `_load_user_config` reads from db.config (not YAML files).
T2.5 — verify scheduler commands no longer accept --config (BREAKING).
"""
from __future__ import annotations

import inspect


def test_load_user_config_reads_db(tmp_path, monkeypatch):
    from polily.cli import _load_user_config
    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB

    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "wallet.starting_balance", 250.0)
    db.close()

    cfg = _load_user_config()
    assert cfg.wallet.starting_balance == 250.0


def test_run_scheduler_does_not_accept_config_flag():
    """v0.10.0 BREAKING: --config flag removed from polily scheduler run."""
    from polily.cli import run_scheduler_daemon

    sig = inspect.signature(run_scheduler_daemon)
    assert "config_path" not in sig.parameters, (
        "--config flag should be deleted in T2.5 (Q2 / BREAKING)"
    )


def test_run_scheduler_loads_config_from_db(tmp_path, monkeypatch):
    """Daemon reads db.config at startup, not yaml."""
    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB

    monkeypatch.chdir(tmp_path)

    # Pre-seed db with non-default
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.magnitude_threshold", 65)
    db.close()

    # Mock run_daemon to capture the config it receives
    captured = {}
    def fake_run_daemon(db, config):
        captured["mag_threshold"] = config.movement.magnitude_threshold

    monkeypatch.setattr("polily.daemon.scheduler.run_daemon", fake_run_daemon)

    from polily.cli import run_scheduler_daemon
    run_scheduler_daemon()

    assert captured["mag_threshold"] == 65


def test_restart_does_not_accept_config_flag():
    """Consistency — drop unused --config from restart subcommand."""
    from polily.cli import restart

    sig = inspect.signature(restart)
    assert "config_path" not in sig.parameters


def test_status_does_not_accept_config_flag():
    """Consistency — drop unused --config from status subcommand."""
    from polily.cli import status

    sig = inspect.signature(status)
    assert "config_path" not in sig.parameters
