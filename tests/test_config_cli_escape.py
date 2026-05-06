"""Tests for `polily config reset` escape hatch (design §7.3 / §11.1 P7)."""
from __future__ import annotations

import pytest
from typer.testing import CliRunner


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """v0.11.0: default_db_path() now resolves via paths.db_path() (env-driven),
    not cwd-relative. Pattern A migration."""
    from polily.core import paths
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    yield
    paths.set_data_dir_override(None)


def test_config_reset_all_clears_all_user_edits(tmp_path):
    from polily.core.config_store import load_all, upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "polily.db"
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
    assert flat["wallet.starting_balance"] == 1000.0


def test_config_reset_single_key(tmp_path):
    from polily.core.config_store import load_all, upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "polily.db"
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


def test_config_reset_unknown_key_exits_nonzero():
    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["config", "reset", "nonexistent.field"])
    assert result.exit_code != 0
