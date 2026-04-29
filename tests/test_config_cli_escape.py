"""Tests for `polily config reset` escape hatch (design §7.3 / §11.1 P7)."""
from __future__ import annotations

from typer.testing import CliRunner


def test_config_reset_all_clears_all_user_edits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import load_all, upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.magnitude_threshold", 50)
    upsert(db, "wallet.starting_balance", 200.0)
    db.close()

    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["config", "reset", "--all", "--yes"])
    assert result.exit_code == 0

    db = PolilyDB(db_path)
    flat = load_all(db)
    db.close()
    assert flat["movement.magnitude_threshold"] == 70  # back to default
    assert flat["wallet.starting_balance"] == 100.0


def test_config_reset_single_key(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import load_all, upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.magnitude_threshold", 50)
    upsert(db, "wallet.starting_balance", 200.0)
    db.close()

    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["config", "reset", "movement.magnitude_threshold"])
    assert result.exit_code == 0

    db = PolilyDB(db_path)
    flat = load_all(db)
    db.close()
    assert flat["movement.magnitude_threshold"] == 70  # reset to default
    assert flat["wallet.starting_balance"] == 200.0  # untouched


def test_config_reset_unknown_key_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["config", "reset", "nonexistent.field"])
    assert result.exit_code != 0
