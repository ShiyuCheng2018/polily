import sqlite3

import pytest

from scanner.core.db import PolilyDB


def test_wallet_table_exists(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(wallet)")}
    assert {"id","cash_usd","starting_balance","topup_total","withdraw_total","created_at","updated_at"} <= cols


def test_positions_composite_key(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(positions)")}
    assert {"market_id","side","event_id","shares","avg_cost","cost_basis","realized_pnl","title","opened_at","updated_at"} <= cols
    pks = [r[1] for r in db.conn.execute("PRAGMA table_info(positions)") if r[5]]
    assert set(pks) == {"market_id","side"}


def test_wallet_transactions_append_only_shape(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(wallet_transactions)")}
    required = {"id","created_at","type","market_id","event_id","side","shares","price",
                "amount_usd","fee_usd","balance_after","realized_pnl","notes"}
    assert required <= cols


def test_events_has_polymarket_category(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(events)")}
    assert "polymarket_category" in cols


def test_wallet_singleton_check(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    db.conn.execute("INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) VALUES (1,100,100,0,0,'t','t')")
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) VALUES (2,50,50,0,0,'t','t')")
        db.conn.commit()


def test_markets_has_resolved_outcome(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(markets)")}
    assert "resolved_outcome" in cols


def test_markets_resolved_outcome_check_constraint(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    db.conn.execute("INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t')")
    db.conn.execute("INSERT INTO markets (market_id,event_id,question,updated_at,resolved_outcome) VALUES ('m1','e1','Q','t','yes')")
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("INSERT INTO markets (market_id,event_id,question,updated_at,resolved_outcome) VALUES ('m2','e1','Q','t','invalid')")
        db.conn.commit()
