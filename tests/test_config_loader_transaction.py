"""SF6 (v0.10.0) — explicit transaction control in load_config_from_db.

Pre-fix code did:

    with db.conn:
        db.conn.execute("BEGIN IMMEDIATE")
        _migrate_yaml_to_db(db)
        ensure_seeded(db)

Two problems:

1. `with db.conn:` already opens an implicit transaction in Python's default
   isolation_level mode. Issuing `BEGIN IMMEDIATE` inside is either no-op or
   — on stricter sqlite + Python combinations — raises
   `OperationalError: cannot start a transaction within a transaction`.
2. `ensure_seeded` itself opens its own `with db.conn:` block, leaving
   transaction nesting visibly inconsistent and contributing to
   developer-confusion bugs.

Post-fix: explicit `BEGIN IMMEDIATE` + `commit()` on the connection,
no `with` wrapper. Tests pin: idempotent calls work, same connection
can be reused, behavior identical under autocommit-style isolation.
"""
from __future__ import annotations

from polily.core.config import load_config_from_db
from polily.core.db import PolilyDB


def test_load_config_from_db_can_be_called_twice_back_to_back(tmp_path):
    """Idempotent — calling load_config_from_db twice in succession on the
    same connection must not raise. If nested-transaction handling were
    wrong, the second BEGIN IMMEDIATE would fail with
    'cannot start a transaction within a transaction'."""
    db = PolilyDB(tmp_path / "polily.db")
    try:
        # First call seeds + migrates
        cfg1 = load_config_from_db(db)
        # Second call must not fail — proves explicit transaction control
        # released the BEGIN IMMEDIATE write lock cleanly the first time.
        cfg2 = load_config_from_db(db)
        assert cfg1.wallet.starting_balance == cfg2.wallet.starting_balance
    finally:
        db.close()


def test_load_config_from_db_works_with_autocommit_isolation(tmp_path, monkeypatch):
    """Belt-and-suspenders: even if a future caller flips
    `db.conn.isolation_level = None` (autocommit), the explicit
    BEGIN IMMEDIATE + commit pair must still work — no implicit
    transaction wrapper means our explicit one is the only one."""
    # v0.11.6: pin paths.data_dir() to tmp_path so _migrate_yaml_to_db
    # doesn't pick up the user's real ~/Library/Application Support
    # config.yaml. Without this, an existing $100 yaml leaks into the
    # tmp db and the new $1000 default-assert fails.
    from polily.core import paths
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))

    db = PolilyDB(tmp_path / "polily.db")
    try:
        # Switch the connection to autocommit mode AFTER schema init
        # so we don't break the schema script. Now `with db.conn:`
        # is a no-op as a transaction wrapper.
        db.conn.isolation_level = None
        cfg = load_config_from_db(db)
        assert cfg is not None
        assert cfg.wallet.starting_balance == 1000.0
    finally:
        db.close()


def test_load_config_from_db_rolls_back_on_seed_failure(tmp_path, monkeypatch):
    """If ensure_seeded raises mid-transaction, the BEGIN IMMEDIATE write
    lock must be released so the next caller / process isn't deadlocked.
    Pre-fix `with db.conn:` would auto-rollback, but only if BEGIN IMMEDIATE
    didn't first conflict with the implicit transaction. Post-fix: explicit
    rollback in the except branch."""
    # v0.11.6: pin paths.data_dir() to tmp_path (see test above).
    from polily.core import paths
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))

    db = PolilyDB(tmp_path / "polily.db")
    try:
        from polily.core import config_store

        original_ensure_seeded = config_store.ensure_seeded
        call_count = {"n": 0}

        def failing_then_ok_seed(db_arg):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("simulated seed failure")
            return original_ensure_seeded(db_arg)

        monkeypatch.setattr(
            "polily.core.config_store.ensure_seeded", failing_then_ok_seed,
        )

        # First call raises — transaction must be rolled back
        import pytest
        with pytest.raises(RuntimeError, match="simulated seed failure"):
            load_config_from_db(db)

        # Second call must succeed — the lock from the first call
        # must have been released. If rollback had failed, we'd hang
        # forever on BEGIN IMMEDIATE here (or get a busy timeout).
        cfg = load_config_from_db(db)
        assert cfg.wallet.starting_balance == 1000.0
    finally:
        db.close()
