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


def test_main_callback_regenerates_yaml_on_tui_launch(tmp_path, monkeypatch):
    """Launching `polily` (no subcommand) overwrites config.yaml from db.

    Per design §4.4 — TUI startup is one of the two yaml regen hooks
    (the other is daemon startup, T3.3)."""
    monkeypatch.chdir(tmp_path)

    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.magnitude_threshold", 42)
    db.close()

    # Mock run_tui to avoid actually launching Textual
    import polily.tui.app as tui_app
    monkeypatch.setattr(tui_app, "run_tui", lambda service=None: None)

    from typer.testing import CliRunner

    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, [])
    assert result.exit_code == 0

    yaml_content = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "magnitude_threshold: 42" in yaml_content
    assert "READ ONLY" in yaml_content


def test_run_scheduler_regenerates_yaml(tmp_path, monkeypatch):
    """daemon startup also regenerates config.yaml from db (per design §4.4).

    Both TUI and daemon paths regen yaml; whichever process starts last
    leaves its snapshot on disk. Both reflect the same db.config so
    content is identical (only the timestamp in the header differs).
    """
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.quality_threshold", 75)
    db.close()

    monkeypatch.setattr(
        "polily.daemon.scheduler.run_daemon", lambda db, config: None
    )

    from polily.cli import run_scheduler_daemon
    run_scheduler_daemon()

    yaml_content = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert "quality_threshold: 75" in yaml_content
    assert "READ ONLY" in yaml_content


# --- S6: launchctl-flavored scheduler subcommand messages -----------------
#
# v0.9.0 made `launchctl list com.polily.scheduler` the single source of
# truth for daemon aliveness; the `data/scheduler.pid` file is no longer
# written. These tests pin user-visible copy in `polily scheduler stop`
# and `polily scheduler status` so it doesn't lie about a "PID file" that
# polily hasn't touched in over a release cycle.


def test_scheduler_stop_message_when_not_running(monkeypatch):
    """`scheduler stop` with no daemon should not mention 'PID file'."""
    from typer.testing import CliRunner

    from polily.cli import app

    monkeypatch.setattr("polily.cli._read_pid", lambda: None)
    # Avoid actual launchctl unload on the test host.
    import subprocess
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, b"", b""),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["scheduler", "stop"])
    assert result.exit_code == 1
    assert "PID file" not in result.stdout
    assert "launchctl" in result.stdout


def test_scheduler_stop_message_when_pid_stale(monkeypatch):
    """Stale PID path: message must reflect launchctl, not a file."""
    from typer.testing import CliRunner

    from polily.cli import app

    monkeypatch.setattr("polily.cli._read_pid", lambda: 12345)
    monkeypatch.setattr("polily.cli._pid_alive", lambda pid: False)
    import subprocess
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, b"", b""),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["scheduler", "stop"])
    assert result.exit_code == 1
    assert "PID file" not in result.stdout
    assert "12345" in result.stdout
    assert "launchctl" in result.stdout


def test_scheduler_status_message_when_not_running(monkeypatch):
    """`scheduler status` with no daemon should not mention 'PID file'."""
    from typer.testing import CliRunner

    from polily.cli import app

    monkeypatch.setattr("polily.cli._read_pid", lambda: None)

    runner = CliRunner()
    result = runner.invoke(app, ["scheduler", "status"])
    assert result.exit_code == 0
    assert "PID file" not in result.stdout
    assert "NOT RUNNING" in result.stdout
    assert "launchctl" in result.stdout


def test_scheduler_status_message_when_pid_stale(monkeypatch):
    """Stale PID via status: launchctl-flavored message, no file unlink."""
    from typer.testing import CliRunner

    from polily.cli import app

    monkeypatch.setattr("polily.cli._read_pid", lambda: 99999)
    monkeypatch.setattr("polily.cli._pid_alive", lambda pid: False)

    runner = CliRunner()
    result = runner.invoke(app, ["scheduler", "status"])
    assert result.exit_code == 0
    assert "PID file" not in result.stdout
    assert "NOT RUNNING" in result.stdout
    assert "99999" in result.stdout
