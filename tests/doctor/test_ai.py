import polily.doctor.checks.ai as ai
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx(tmp_path, live=False, platform="darwin"):
    return DoctorContext(data_dir=tmp_path, db_path=tmp_path / "polily.db",
                         log_dir=tmp_path / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform=platform, live=live)


def _by_id(rs, cid):
    return next(r for r in rs if r.id == cid)


def test_claude_missing_warns(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: None)
    r = _by_id(ai.ai_checks(_ctx(tmp_path)), "ai.claude_cli")
    assert r.severity == Severity.WARN


def test_live_probe_skipped_without_flag(tmp_path, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")
    r = _by_id(ai.ai_checks(_ctx(tmp_path, live=False)), "ai.live_probe")
    assert r.severity == Severity.SKIPPED


def test_recent_failures_warn(seeded_db, monkeypatch):
    monkeypatch.setattr("shutil.which", lambda x: "/usr/bin/claude")
    seeded_db.conn.execute(
        "INSERT INTO scan_logs(scan_id,type,status,started_at,finished_at,error) "
        "VALUES('s1','analyze','failed',datetime('now'),datetime('now'),'[API 401] auth')")
    seeded_db.conn.commit()
    ctx = DoctorContext(data_dir=seeded_db.db_path.parent, db_path=seeded_db.db_path,
                        log_dir=seeded_db.db_path.parent / "logs", data_dir_tier="env",
                        launchd_label="com.polily.scheduler", platform="darwin")
    r = _by_id(ai.ai_checks(ctx), "ai.recent_failures")
    assert r.severity in (Severity.WARN, Severity.CRITICAL)
