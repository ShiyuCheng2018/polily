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


def test_polily_db_open_never_triggers_config_load(tmp_path, monkeypatch):
    """B2 (v0.10.0) — `_ensure_wallet_singleton` must NOT call
    `load_config_from_db`, on either fresh or steady-state opens.

    Pre-fix: the wallet seed path called `load_config_from_db(self)`,
    which acquires `BEGIN IMMEDIATE`. From inside `__init__` this
    re-entered the same connection's transaction state and let the
    TUI+daemon first-init race deadlock. It also forced every test
    using `PolilyDB(tmp_path / ...)` to pay a 46-row config seed.

    Post-fix: wallet seed reads `wallet.starting_balance` directly from
    the config table (or falls back to `WalletConfig()` Pydantic
    default if the row isn't present). Callers (cli.py / tui/service /
    daemon) explicitly invoke `load_config_from_db` after construction.
    """
    from polily.core import config as config_module
    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB

    # Instrument to detect any sneaky re-entry into load_config_from_db.
    call_count = {"n": 0}
    real_fn = config_module.load_config_from_db

    def counting_load_config(db):
        call_count["n"] += 1
        return real_fn(db)

    monkeypatch.setattr(config_module, "load_config_from_db", counting_load_config)

    # Fresh file → wallet seed runs on the cold path. Must NOT load config.
    db1 = PolilyDB(tmp_path / "polily.db")
    try:
        assert call_count["n"] == 0, (
            f"Fresh-init PolilyDB.__init__ called load_config_from_db "
            f"{call_count['n']} time(s) — B2 regression. The wallet seed "
            f"path must read wallet.starting_balance directly, not via "
            f"load_config_from_db."
        )
        # User explicitly seeds + edits — this DOES call load_config_from_db
        # via the public API; not under test here.
        upsert(db1, "movement.magnitude_threshold", 50)
    finally:
        db1.close()

    # Reset counter for the warm path
    call_count["n"] = 0

    # Second open: wallet exists, early-return on the SELECT.
    db2 = PolilyDB(tmp_path / "polily.db")
    try:
        assert call_count["n"] == 0, (
            f"Steady-state PolilyDB.__init__ called load_config_from_db "
            f"{call_count['n']} time(s) — perf regression."
        )
    finally:
        db2.close()


def test_wallet_seed_uses_pydantic_default_when_config_table_empty(tmp_path):
    """B2 (v0.10.0) — when config table has no `wallet.starting_balance`
    row (the very first init, before anyone has explicitly called
    `load_config_from_db`), wallet seed falls back to the Pydantic
    default from `WalletConfig()`.

    This pins the new contract: PolilyDB.__init__ no longer migrates yaml
    or seeds config; the wallet row uses the in-memory Pydantic default.
    The caller (cli.py / tui app) is responsible for explicitly calling
    load_config_from_db afterwards if it wants to pick up user edits.
    """
    from polily.core.config import WalletConfig
    from polily.core.db import PolilyDB

    db = PolilyDB(tmp_path / "polily.db")
    try:
        # Config table is empty (no explicit load_config_from_db call yet).
        config_row_count = db.conn.execute(
            "SELECT COUNT(*) FROM config"
        ).fetchone()[0]
        assert config_row_count == 0, (
            "PolilyDB.__init__ should NOT seed config — caller is "
            "responsible for that via explicit load_config_from_db()."
        )

        # Wallet still got seeded with the Pydantic default.
        cur = db.conn.execute(
            "SELECT cash_usd, starting_balance FROM wallet WHERE id = 1"
        )
        cash, starting = cur.fetchone()
        expected = WalletConfig().starting_balance  # 100.0
        assert starting == expected
        assert cash == expected
    finally:
        db.close()


def test_wallet_seed_reads_existing_config_row_when_present(tmp_path):
    """B2 — when `wallet.starting_balance` is already in db.config (e.g.
    a prior caller invoked `load_config_from_db` earlier in this process),
    a fresh wallet seed picks it up rather than the Pydantic default."""
    from polily.core.db import PolilyDB

    db = PolilyDB(tmp_path / "polily.db")
    try:
        # User explicitly seeds the config table + sets a custom value
        # via the public API. PolilyDB.__init__ already seeded the wallet
        # with the Pydantic default; we delete + reseed to simulate a
        # fresh init order where config row is present BEFORE wallet seed.
        from polily.core.config_store import upsert
        upsert(db, "wallet.starting_balance", 250.0)
        db.conn.execute("DELETE FROM wallet")
        db.conn.commit()

        db._ensure_wallet_singleton()
        cur = db.conn.execute(
            "SELECT cash_usd, starting_balance FROM wallet WHERE id = 1"
        )
        cash, starting = cur.fetchone()
        assert starting == 250.0
        assert cash == 250.0
    finally:
        db.close()
