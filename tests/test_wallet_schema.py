import sqlite3

import pytest

from scanner.core.db import PolilyDB


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def test_wallet_table_exists(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(wallet)")}
    assert {
        "id",
        "cash_usd",
        "starting_balance",
        "topup_total",
        "withdraw_total",
        "created_at",
        "updated_at",
    } <= cols


def test_positions_composite_key(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(positions)")}
    assert {
        "market_id",
        "side",
        "event_id",
        "shares",
        "avg_cost",
        "cost_basis",
        "realized_pnl",
        "title",
        "opened_at",
        "updated_at",
    } <= cols
    pks = [r[1] for r in db.conn.execute("PRAGMA table_info(positions)") if r[5]]
    assert set(pks) == {"market_id", "side"}


def test_wallet_transactions_append_only_shape(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(wallet_transactions)")}
    required = {
        "id",
        "created_at",
        "type",
        "market_id",
        "event_id",
        "side",
        "shares",
        "price",
        "amount_usd",
        "fee_usd",
        "balance_after",
        "realized_pnl",
        "notes",
    }
    assert required <= cols


def test_events_has_polymarket_category(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(events)")}
    assert "polymarket_category" in cols


def test_wallet_singleton_check(db):
    # Auto-migration in PolilyDB.__init__ already inserted wallet at id=1,
    # so we only need to verify id=2 is rejected by the CHECK(id=1) constraint.
    existing = db.conn.execute("SELECT id FROM wallet WHERE id=1").fetchone()
    assert existing is not None, "auto-migration should have created id=1"
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) "
            "VALUES (2,50,50,0,0,'t','t')"
        )
        db.conn.commit()


def test_markets_has_resolved_outcome(db):
    cols = {r[1] for r in db.conn.execute("PRAGMA table_info(markets)")}
    assert "resolved_outcome" in cols


def test_markets_resolved_outcome_check_constraint(db):
    db.conn.execute("INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t')")
    db.conn.execute(
        "INSERT INTO markets (market_id,event_id,question,updated_at,resolved_outcome) VALUES ('m1','e1','Q','t','yes')"
    )
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO markets (market_id,event_id,question,updated_at,resolved_outcome) "
            "VALUES ('m2','e1','Q','t','invalid')"
        )
        db.conn.commit()


def test_wallet_transactions_type_check_rejects_unknown(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO wallet_transactions (created_at,type,amount_usd,balance_after) VALUES ('t','INVALID_TYPE',0,0)"
        )
        db.conn.commit()


def test_positions_side_check_rejects_invalid(db):
    db.conn.execute("INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t')")
    db.conn.execute("INSERT INTO markets (market_id,event_id,question,updated_at) VALUES ('m1','e1','Q','t')")
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO positions (market_id,side,event_id,shares,avg_cost,cost_basis,title,opened_at,updated_at) "
            "VALUES ('m1','MAYBE','e1',10,0.5,5,'Q','t','t')"
        )
        db.conn.commit()


def test_positions_fk_rejects_missing_market(db):
    db.conn.execute("INSERT INTO events (event_id,title,updated_at) VALUES ('e1','E','t')")
    db.conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute(
            "INSERT INTO positions (market_id,side,event_id,shares,avg_cost,cost_basis,title,opened_at,updated_at) "
            "VALUES ('ghost_market','yes','e1',10,0.5,5,'Q','t','t')"
        )
        db.conn.commit()
