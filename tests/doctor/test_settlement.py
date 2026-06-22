import polily.doctor.checks.settlement as st
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx_for(db):
    return DoctorContext(data_dir=db.db_path.parent, db_path=db.db_path,
                         log_dir=db.db_path.parent / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform="darwin")


def _seed_event_market(db, mid, closed, resolved):
    db.conn.execute("INSERT OR IGNORE INTO events(event_id,title,updated_at) VALUES('e','E','t')")
    db.conn.execute(
        "INSERT INTO markets(market_id,event_id,question,closed,resolved_outcome,end_date,updated_at)"
        " VALUES(?, 'e','Q',?,?, '2020-01-01T00:00:00+00:00','t')", (mid, closed, resolved))
    db.conn.commit()


def _by_id(rs, cid):
    return next(r for r in rs if r.id == cid)


def test_stuck_resolution_past_window_warns(seeded_db):
    _seed_event_market(seeded_db, "m1", 1, None)  # closed, unresolved, end_date 2020 (past)
    r = _by_id(st.settlement_checks(_ctx_for(seeded_db)), "settle.stuck_resolutions")
    assert r.severity in (Severity.WARN, Severity.CRITICAL)
    assert r.value["stuck"] >= 1


def test_no_stuck_is_ok(seeded_db):
    _seed_event_market(seeded_db, "m1", 1, "yes")
    r = _by_id(st.settlement_checks(_ctx_for(seeded_db)), "settle.stuck_resolutions")
    assert r.severity == Severity.OK


def test_position_on_resolved_market_critical(seeded_db):
    _seed_event_market(seeded_db, "m1", 1, "yes")
    seeded_db.conn.execute(
        "INSERT INTO positions(market_id,side,event_id,shares,avg_cost,cost_basis,title,"
        "opened_at,updated_at) VALUES('m1','no','e',10,0.5,5.0,'Q','t','t')")
    seeded_db.conn.commit()
    r = _by_id(st.settlement_checks(_ctx_for(seeded_db)), "settle.positions_on_settled")
    assert r.severity == Severity.CRITICAL
