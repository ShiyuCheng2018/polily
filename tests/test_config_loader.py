"""Tests for the new zero-arg load_config_from_db() that reads from db.config."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from polily.core.config import (
    ConfigValidationError,
    PolilyConfig,
    load_config_from_db,
)
from polily.core.config_store import ensure_seeded, upsert
from polily.core.db import PolilyDB


def test_default_db_path_returns_pydantic_default():
    """default_db_path() returns the Pydantic default for archiving.db_file."""
    from polily.core.config import default_db_path
    expected = Path("./data/polily.db")
    assert default_db_path() == expected


def test_default_db_path_ignores_db_config_override(tmp_path, monkeypatch):
    """Whis SF11 — even if archiving.db_file is set in db.config, the helper
    still returns the Pydantic default. Documents the chicken-and-egg rule."""
    from polily.core.config import default_db_path

    # Pre-create a db with a non-default archiving.db_file value
    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "archiving.db_file", "/some/custom/path/polily.db")
    db.close()

    # default_db_path should STILL return the Pydantic default,
    # NOT the value we put in db.config
    assert default_db_path() == Path("./data/polily.db")


def test_load_config_from_db_returns_polily_config_with_defaults(polily_db):
    """Empty db gets seeded; load returns PolilyConfig with all defaults."""
    config = load_config_from_db(polily_db)
    assert isinstance(config, PolilyConfig)
    assert config.movement.magnitude_threshold == 70
    assert config.wallet.starting_balance == 100.0


def test_load_config_from_db_reflects_user_edits(polily_db):
    """Edited db value comes back in the loaded PolilyConfig."""
    ensure_seeded(polily_db)
    upsert(polily_db, "movement.magnitude_threshold", 50)

    config = load_config_from_db(polily_db)
    assert config.movement.magnitude_threshold == 50


def test_load_config_from_db_recomputes_user_agent(polily_db):
    """api.user_agent is EPHEMERAL — Pydantic default_factory follows __version__."""
    from polily import __version__
    ensure_seeded(polily_db)

    config = load_config_from_db(polily_db)
    assert config.api.user_agent == f"polily/{__version__}"


def test_load_config_from_db_raises_on_validation_failure(polily_db):
    """If db has out-of-range value, raise ConfigValidationError (no fallback).

    Tests AC3 — fail-loud philosophy."""
    ensure_seeded(polily_db)
    # Force an invalid wallet.starting_balance (Field has ge=1.0)
    polily_db.conn.execute(
        "UPDATE config SET value = ? WHERE key_path = ?",
        (json.dumps(0.0), "wallet.starting_balance"),
    )
    polily_db.conn.commit()

    with pytest.raises(ConfigValidationError):
        load_config_from_db(polily_db)


def test_load_config_from_db_runs_yaml_migration_first(tmp_path, monkeypatch):
    """Whis B3 — legacy yaml values win over Pydantic defaults on first run."""
    monkeypatch.chdir(tmp_path)
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )
    db = PolilyDB(tmp_path / "polily.db")
    try:
        config = load_config_from_db(db)
        assert config.wallet.starting_balance == 250.0  # NOT 100.0 default
    finally:
        db.close()


def test_load_config_from_db_atomic_migrate_then_seed_under_concurrency(tmp_path):
    """AC1 — cross-process race: process B's ensure_seeded must NOT
    interleave between process A's migrate count-check and migrate insert.
    BEGIN IMMEDIATE serializes them so user yaml customization wins.

    Simulated within one Python process by 4 threads each opening their
    own PolilyDB on same db file with a yaml that has user values.
    After all complete, assert user values won (250.0), not Pydantic
    default (100.0).

    Note: PolilyDB() construction itself isn't safe for parallel creation
    on a fresh file (writes initial wallet row, runs migrations). We
    pre-create the schema by opening+closing one PolilyDB before
    spawning the racing threads — this matches the real-world v0.10.0
    upgrade scenario where the db file already exists from v0.9.x and
    only the new `config` table needs to be populated.
    """
    db_path = tmp_path / "polily.db"
    yaml_path = tmp_path / "config.yaml"
    yaml_path.write_text(
        "wallet:\n  starting_balance: 250.0\n", encoding="utf-8",
    )

    # Pre-create schema (single-threaded). This leaves config table
    # empty so the upgrade-style race is the one tested.
    seed_db = PolilyDB(db_path)
    # Phase 2 / Task 2.2 made PolilyDB.__init__ auto-trigger
    # load_config_from_db via the wallet seed path. That populates
    # config with Pydantic defaults *before* the racing threads spawn,
    # which would mask the AC1 race we're trying to detect (migration
    # would short-circuit on populated table). Wipe to restore the
    # upgrade-style empty-config-table precondition.
    seed_db.conn.execute("DELETE FROM config")
    seed_db.conn.commit()
    seed_db.close()

    # All threads must run in tmp_path so each finds the yaml
    import os
    original_cwd = os.getcwd()
    os.chdir(tmp_path)

    errors = []
    results = []

    def worker():
        try:
            db = PolilyDB(db_path)
            try:
                config = load_config_from_db(db)
                results.append(config.wallet.starting_balance)
            finally:
                db.close()
        except Exception as e:
            errors.append(e)

    try:
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        os.chdir(original_cwd)

    assert not errors, f"load_config_from_db raised under concurrency: {errors}"
    # All 4 threads must see the user's yaml value, not the Pydantic default.
    # If BEGIN IMMEDIATE failed to serialize, some races would write defaults
    # before migration, and those threads would observe 100.0.
    assert all(v == 250.0 for v in results), (
        f"AC1 race detected: some threads saw Pydantic defaults instead "
        f"of user yaml. Results: {results}"
    )
