import polily.doctor.checks.database as dbc
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx_for(db, deep=False):
    return DoctorContext(data_dir=db.db_path.parent, db_path=db.db_path,
                         log_dir=db.db_path.parent / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform="darwin", deep=deep)


def _ctx_missing(tmp_path):
    return DoctorContext(data_dir=tmp_path, db_path=tmp_path / "nope.db",
                         log_dir=tmp_path / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform="darwin")


def _by_id(rs, cid):
    return next(r for r in rs if r.id == cid)


def test_openable_critical_when_missing(tmp_path):
    r = _by_id(dbc.database_checks(_ctx_missing(tmp_path)), "db.openable")
    assert r.severity == Severity.CRITICAL


def test_quick_check_ok_on_seeded(seeded_db):
    r = _by_id(dbc.database_checks(_ctx_for(seeded_db)), "db.integrity")
    assert r.severity == Severity.OK


def test_schema_present_on_seeded(seeded_db):
    r = _by_id(dbc.database_checks(_ctx_for(seeded_db)), "db.schema")
    assert r.severity == Severity.OK


def test_wal_mode_on_seeded(seeded_db):
    r = _by_id(dbc.database_checks(_ctx_for(seeded_db)), "db.wal_mode")
    assert r.severity == Severity.OK
