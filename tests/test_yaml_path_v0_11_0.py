"""v0.11.0 — config.yaml resolves to paths.data_dir() / config.yaml,
not cwd-relative. Affects yaml regen (write) AND yaml→db migration (read).

Pre-v0.11.0 the yaml file lived at ``$CWD/config.yaml`` — fragile under
pipx installs (cwd is wherever the user ran the command, often a
read-only or unrelated directory). Post-v0.11.0 yaml lives next to the
db at ``paths.data_dir() / 'config.yaml'``.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Per-test env isolation: clear CLI override, pin POLILY_DATA_DIR
    to a per-test tmp dir, restore on teardown."""
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily"))
    yield
    paths.set_data_dir_override(None)


def test_yaml_regen_writes_to_paths_data_dir(tmp_path):
    """``_regenerate_yaml_snapshot`` writes to ``<data_dir>/config.yaml``."""
    from polily.cli import _regenerate_yaml_snapshot
    from polily.core.config import PolilyConfig

    config = PolilyConfig()
    _regenerate_yaml_snapshot(config)

    expected = tmp_path / "polily" / "config.yaml"
    assert expected.exists(), f"yaml not at {expected}; cwd={Path.cwd()}"


def test_yaml_migration_reads_from_paths_data_dir(monkeypatch, tmp_path):
    """``_migrate_yaml_to_db`` reads from ``<data_dir>/config.yaml``,
    not cwd. Pin: chdir to a YAML-FREE dir so a stray cwd-rel
    ``config.yaml`` (e.g. dev workdir) cannot make the test pass for
    the wrong reason."""
    from polily.core.config_store import _migrate_yaml_to_db
    from polily.core.db import PolilyDB

    # Clean cwd guarantees: if production code reads cwd, status would be
    # ('skipped_no_yaml',) — assertion below would fail. Only the
    # data_dir-rel read path produces ('ok', N).
    cwd_clean = tmp_path / "cwd_no_yaml"
    cwd_clean.mkdir()
    monkeypatch.chdir(cwd_clean)

    yaml_dir = tmp_path / "polily"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    (yaml_dir / "config.yaml").write_text(
        "movement:\n  magnitude_threshold: 55\n",
        encoding="utf-8",
    )

    db = PolilyDB(tmp_path / "polily.db")
    try:
        # PolilyDB.__init__ may auto-seed config; wipe so migration sees
        # an empty table (the real v0.9.x → v0.10.0 upgrade case).
        db.conn.execute("DELETE FROM config")
        db.conn.commit()
        status = _migrate_yaml_to_db(db)
        assert status[0] == "ok", f"unexpected status: {status}"
        assert status[1] >= 1
    finally:
        db.close()
