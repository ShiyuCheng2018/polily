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
