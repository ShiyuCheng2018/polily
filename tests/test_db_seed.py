"""Tests for db.py wallet seeding via the new zero-arg load_config_from_db.

Phase 2 / Task 2.2 of v0.10.0 TUI-config rollout:
`PolilyDB._ensure_wallet_singleton` migrated from yaml-fallback chain
(config.minimal.yaml + config.example.yaml) to db-canonical config
(`load_config_from_db(self)`). After this migration, a user-edited
wallet.starting_balance value in the db.config table is honored on the
next wallet (re-)seed without requiring yaml files on disk.
"""
from __future__ import annotations

from polily.core.config_store import upsert
from polily.core.db import PolilyDB


def test_seed_wallet_uses_db_canonical_starting_balance(tmp_path):
    """When user has set wallet.starting_balance=200 in db, wallet seed uses it.

    `__init__` already seeded the wallet row with the Pydantic default
    (100.0). We then upsert the new value, delete the wallet row to
    simulate a fresh re-seed (e.g., post-reset), and call
    `_ensure_wallet_singleton` again. The new value must be picked up.
    """
    db = PolilyDB(tmp_path / "polily.db")
    try:
        upsert(db, "wallet.starting_balance", 200.0)
        # __init__ already seeded with 100.0; reset to test new starting_balance.
        db.conn.execute("DELETE FROM wallet")
        db.conn.commit()
        db._ensure_wallet_singleton()  # should pick up the user-edited 200.0
        cur = db.conn.execute(
            "SELECT cash_usd, starting_balance FROM wallet WHERE id = 1"
        )
        cash, starting = cur.fetchone()
        assert starting == 200.0
        assert cash == 200.0
    finally:
        db.close()


def test_steady_state_polily_db_open_skips_config_load(tmp_path, monkeypatch):
    """Once wallet row exists, opening PolilyDB again must NOT trigger
    config seeding (BEGIN IMMEDIATE + 46 INSERT OR IGNORE).

    Pins the current invariant: _ensure_wallet_singleton's wallet SELECT
    + early-return is positioned BEFORE the load_config_from_db call.
    A future refactor that reorders these (e.g., to use cfg.wallet.foo
    in the wallet check) would silently make every TUI/CLI startup pay
    the BEGIN IMMEDIATE write-lock cost.
    """
    from polily.core.config_store import load_all, upsert
    from polily.core.db import PolilyDB

    # First open: fresh file → wallet seeded + config seeded (47 - 1 ephemeral = 46)
    db1 = PolilyDB(tmp_path / "polily.db")
    try:
        # Verify config table got seeded on first open (cold path)
        assert len(load_all(db1)) == 46
        # User edits a value
        upsert(db1, "movement.magnitude_threshold", 50)
    finally:
        db1.close()

    # Second open: wallet exists → config seed should NOT run.
    # Instrument by counting load_config_from_db invocations.
    call_count = {"n": 0}
    from polily.core import config as config_module
    real_fn = config_module.load_config_from_db

    def counting_load_config(db):
        call_count["n"] += 1
        return real_fn(db)

    monkeypatch.setattr(config_module, "load_config_from_db", counting_load_config)

    db2 = PolilyDB(tmp_path / "polily.db")
    try:
        # Steady-state: wallet existed → load_config_from_db must NOT
        # have been called from _ensure_wallet_singleton during __init__.
        assert call_count["n"] == 0, (
            f"Steady-state PolilyDB.__init__ called load_config_from_db "
            f"{call_count['n']} time(s) — perf regression. The wallet-row "
            f"early-return at db.py:370-372 must short-circuit before any "
            f"config load."
        )
        # User's edit still there (sanity check that we're testing the right db)
        flat = load_all(db2)
        assert flat["movement.magnitude_threshold"] == 50
    finally:
        db2.close()
