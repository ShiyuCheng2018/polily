import polily.doctor.checks.wallet as wc
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx_for(db):
    return DoctorContext(data_dir=db.db_path.parent, db_path=db.db_path,
                         log_dir=db.db_path.parent / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform="darwin")


def _by_id(rs, cid):
    return next(r for r in rs if r.id == cid)


def test_clean_wallet_reconciles(seeded_db):
    # PolilyDB seeds the wallet singleton; a freshly-seeded wallet reconciles.
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "wallet.cash_reconciles")
    assert r.severity == Severity.OK


def test_real_ledger_reconciles(seeded_db):
    # Prove the SUM(amount_usd) sign convention: BUY(-cost) + FEE(-fee) + SELL(+proceeds).
    conn = seeded_db.conn
    start = conn.execute("SELECT starting_balance FROM wallet WHERE id=1").fetchone()[0]
    bal = start
    for typ, amt, pnl in [("BUY", -6.0, None), ("FEE", -0.2, None), ("SELL", 9.0, 3.0)]:
        bal += amt
        conn.execute(
            "INSERT INTO wallet_transactions"
            "(created_at,type,amount_usd,fee_usd,balance_after,realized_pnl) "
            "VALUES('t',?,?,0,?,?)", (typ, amt, bal, pnl))
    conn.execute("UPDATE wallet SET cash_usd=? WHERE id=1", (bal,))
    conn.commit()
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "wallet.cash_reconciles")
    assert r.severity == Severity.OK


def test_cash_drift_is_critical(seeded_db):
    seeded_db.conn.execute("UPDATE wallet SET cash_usd = cash_usd + 999 WHERE id = 1")
    seeded_db.conn.commit()
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "wallet.cash_reconciles")
    assert r.severity == Severity.CRITICAL


def test_cost_basis_drift_critical(seeded_db):
    seeded_db.conn.execute("INSERT OR IGNORE INTO events(event_id,title,updated_at) VALUES('e','E','t')")
    seeded_db.conn.execute(
        "INSERT INTO markets(market_id,event_id,question,updated_at) VALUES('m','e','Q','t')")
    seeded_db.conn.execute(
        "INSERT INTO positions(market_id,side,event_id,shares,avg_cost,cost_basis,title,"
        "opened_at,updated_at) VALUES('m','yes','e',10,0.5,999.0,'Q','t','t')")  # 999 != 10*0.5
    seeded_db.conn.commit()
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "positions.cost_basis")
    assert r.severity == Severity.CRITICAL


def test_singleton_missing_critical(seeded_db):
    seeded_db.conn.execute("DELETE FROM wallet WHERE id=1")
    seeded_db.conn.commit()
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "wallet.singleton")
    assert r.severity == Severity.CRITICAL


def test_migrated_wallet_reconciles(seeded_db):
    # Opening balance seeded as a MIGRATION ledger row (opening=0 in the ledger),
    # AND duplicated in starting_balance. Must NOT be double-counted → OK.
    conn = seeded_db.conn
    conn.execute("UPDATE wallet SET starting_balance=100.0, cash_usd=30.0 WHERE id=1")
    for typ, amt, bal in [("MIGRATION", 100.0, 100.0), ("BUY", -70.0, 30.0)]:
        conn.execute(
            "INSERT INTO wallet_transactions(created_at,type,amount_usd,fee_usd,balance_after) "
            "VALUES('t',?,?,0,?)", (typ, amt, bal))
    conn.commit()
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "wallet.cash_reconciles")
    # cash 30 == implied_opening(0) + SUM(100-70); the OLD formula gave starting(100)+30=130 → false CRITICAL
    assert r.severity == Severity.OK


def test_orphan_positions_critical(seeded_db):
    seeded_db.conn.execute("PRAGMA foreign_keys=OFF")
    seeded_db.conn.execute("INSERT OR IGNORE INTO events(event_id,title,updated_at) VALUES('e','E','t')")
    seeded_db.conn.execute(
        "INSERT INTO positions(market_id,side,event_id,shares,avg_cost,cost_basis,title,opened_at,updated_at) "
        "VALUES('ghost','yes','e',10,0.5,5.0,'Q','t','t')")
    seeded_db.conn.commit()
    r = _by_id(wc.wallet_checks(_ctx_for(seeded_db)), "positions.orphans")
    assert r.severity == Severity.CRITICAL
