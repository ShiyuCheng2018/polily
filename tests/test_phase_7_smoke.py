"""Phase 7 smoke test — full happy path through the new config system.

Pins the v0.10.0 contract end-to-end so future refactors can't silently
break the user-visible flow:

1. Fresh install (empty data dir) → polily seeds db.config with defaults
2. yaml is regenerated on TUI launch with READ ONLY header
3. User edits a knob via the save_knob path
4. db.config has the new value
5. polily config reset <key> walks it back to the Pydantic default
6. Coverage gate is still green (40 territory A docs)

Anything that breaks one of these steps either ships a bug or needs an
intentional CHANGELOG-documented contract change.
"""
from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner


def test_phase_7_full_happy_path(tmp_path, monkeypatch):
    # v0.11.0 (Task 7 done): yaml regen + db path both resolve via paths
    # module. Since POLILY_DATA_DIR == tmp_path, the existing yaml_path
    # = Path("config.yaml") assertion below still works because cwd ==
    # tmp_path == data_dir. chdir kept additively per Whis-review S8 to
    # avoid churn until Task 8.
    from polily.core import paths
    paths.set_data_dir_override(None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))

    try:
        # 1. Fresh install — TUI launch (mocked) seeds db + writes yaml.
        #    No subcommand → `main` callback runs → builds PolilyService
        #    (which seeds db.config via load_config_from_db) → writes yaml
        #    snapshot → invokes the mocked run_tui which is a no-op.
        monkeypatch.setattr("polily.tui.app.run_tui", lambda service=None: None)
        from polily.cli import app
        runner = CliRunner()
        result = runner.invoke(app, [])  # no subcommand → main callback runs
        assert result.exit_code == 0, result.output

        # 2. yaml exists with READ ONLY header + a known default value.
        yaml_path = Path("config.yaml")
        assert yaml_path.exists()
        yaml_text = yaml_path.read_text(encoding="utf-8")
        assert "READ ONLY" in yaml_text
        assert "magnitude_threshold: 70" in yaml_text

        # 3. db.config has 46 rows (47 leaves - 1 EPHEMERAL).
        from polily.core.config_store import load_all
        from polily.core.db import PolilyDB

        db_path = tmp_path / "polily.db"
        db = PolilyDB(db_path)
        flat = load_all(db)
        db.close()
        assert len(flat) == 46
        assert "api.user_agent" not in flat  # EPHEMERAL never persisted

        # 4. Edit via save_knob (simulating Edit modal save handler).
        from polily.core.config import save_knob

        db = PolilyDB(db_path)
        save_knob(db, "movement.magnitude_threshold", 50)
        flat = load_all(db)
        assert flat["movement.magnitude_threshold"] == 50
        db.close()

        # 5. polily config reset walks it back to the Pydantic default.
        result = runner.invoke(app, ["config", "reset", "movement.magnitude_threshold"])
        assert result.exit_code == 0, result.output

        db = PolilyDB(db_path)
        flat = load_all(db)
        db.close()
        assert flat["movement.magnitude_threshold"] == 70

        # 6. Coverage gate — 40 territory A keys still have markdown docs.
        from polily.core.config_docs import load_all as load_docs

        docs = load_docs()
        assert len(docs) == 40
    finally:
        paths.set_data_dir_override(None)
