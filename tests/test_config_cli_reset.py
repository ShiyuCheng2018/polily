"""SF3 — `polily config reset --all` must be atomic + prompt for daemon restart.

Background: previous impl was

    db.conn.execute("DELETE FROM config")
    db.conn.commit()
    ensure_seeded(db)

Two problems:

1. Not transactional. A daemon poll tick that fires between the
   commit and ensure_seeded sees an empty config table and either
   crashes or operates on stale in-memory snapshot — depending on the
   code path.

2. No daemon restart hint. Even after a successful reset, the daemon's
   in-memory `PolilyConfig` snapshot continues to use the pre-reset
   values until restart. Users don't know that.

Fix:

1. Wrap DELETE + ensure_seeded in BEGIN IMMEDIATE — same pattern as
   `load_config_from_db` (which faces the same cross-process race).
2. Print a one-line restart hint after success.
"""
from __future__ import annotations

from typer.testing import CliRunner


def test_reset_all_is_atomic_on_seed_failure(tmp_path, monkeypatch):
    """Simulate `ensure_seeded` raising mid-reset. The DELETE must be
    rolled back so config is not left empty — otherwise a daemon poll
    tick concurrent with the failed reset operates on no config rows.
    """
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import load_all, upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.magnitude_threshold", 50)
    upsert(db, "wallet.starting_balance", 200.0)
    pre_reset = load_all(db)
    db.close()

    # Force ensure_seeded to raise mid-reset.
    def boom(_db):
        raise RuntimeError("simulated seed failure")

    # Monkeypatch the binding the CLI imports lazily — patch the source.
    from polily.core import config_store
    monkeypatch.setattr(config_store, "ensure_seeded", boom)

    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["config", "reset", "--all", "--yes"])
    # CLI surfaces the error
    assert result.exit_code != 0

    # CRITICAL: config table must be unchanged from pre-reset state.
    # Without BEGIN IMMEDIATE, the DELETE would have committed and the
    # table would now be empty.
    db = PolilyDB(db_path)
    post_failure = load_all(db)
    db.close()
    assert post_failure == pre_reset, (
        "DELETE must roll back when ensure_seeded fails — otherwise "
        "concurrent readers see an empty config table"
    )


def test_reset_all_prints_restart_hint(tmp_path, monkeypatch):
    """After successful --all reset, output must remind user to restart
    the daemon so its in-memory config snapshot picks up the new values.
    """
    monkeypatch.chdir(tmp_path)
    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "movement.magnitude_threshold", 50)
    db.close()

    from polily.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["config", "reset", "--all", "--yes"])
    assert result.exit_code == 0
    # Restart hint must be present in the user-visible output.
    assert "scheduler restart" in result.stdout
