"""Wallet config tests — db-canonical (post-v0.10.0).

Yaml-as-input is gone (T7.4); the only ways `wallet.starting_balance` reaches
the runtime are (1) Pydantic default and (2) a user-edited row in db.config.
"""
from polily.core.config import PolilyConfig, load_config_from_db
from polily.core.config_store import upsert
from polily.core.db import PolilyDB


def test_wallet_config_default():
    cfg = PolilyConfig()
    assert cfg.wallet.starting_balance == 100.0


def test_wallet_config_override(tmp_path):
    """User-edited db.config row overrides the Pydantic default."""
    db = PolilyDB(tmp_path / "polily.db")
    try:
        upsert(db, "wallet.starting_balance", 250.0)
        cfg = load_config_from_db(db)
        assert cfg.wallet.starting_balance == 250.0
    finally:
        db.close()
