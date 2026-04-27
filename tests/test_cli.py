"""Tests for `polily/cli.py` helpers.

T2.4 — verify `_load_user_config` reads from db.config (not YAML files).
"""
from __future__ import annotations


def test_load_user_config_reads_db(tmp_path, monkeypatch):
    from polily.cli import _load_user_config
    from polily.core.config_store import upsert
    from polily.core.db import PolilyDB

    monkeypatch.chdir(tmp_path)
    db_path = tmp_path / "data" / "polily.db"
    db_path.parent.mkdir(exist_ok=True)
    db = PolilyDB(db_path)
    upsert(db, "wallet.starting_balance", 250.0)
    db.close()

    cfg = _load_user_config()
    assert cfg.wallet.starting_balance == 250.0
