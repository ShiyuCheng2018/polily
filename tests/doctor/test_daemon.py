import polily.doctor.checks.daemon as dmn
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx(tmp_path, platform="darwin"):
    return DoctorContext(data_dir=tmp_path, db_path=tmp_path / "polily.db",
                         log_dir=tmp_path / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler.dev", platform=platform)


def _by_id(rs, cid):
    return next(r for r in rs if r.id == cid)


def test_all_skipped_off_darwin(tmp_path):
    rs = dmn.daemon_checks(_ctx(tmp_path, platform="linux"))
    assert all(r.severity == Severity.SKIPPED for r in rs)


def test_registered_critical_when_not_running(tmp_path, monkeypatch):
    monkeypatch.setattr(dmn, "_is_running", lambda: False)  # no-arg signature
    r = _by_id(dmn.daemon_checks(_ctx(tmp_path)), "daemon.registered")
    assert r.severity == Severity.CRITICAL


def test_polling_fresh_stale_is_critical(tmp_path, monkeypatch):
    monkeypatch.setattr(dmn, "_is_running", lambda: True)
    monkeypatch.setattr(dmn, "_monitored_freshness", lambda ctx: (1, 600.0))  # 10 min old
    r = _by_id(dmn.daemon_checks(_ctx(tmp_path)), "daemon.polling_fresh")
    assert r.severity == Severity.CRITICAL


def test_polling_fresh_info_when_no_monitored(tmp_path, monkeypatch):
    monkeypatch.setattr(dmn, "_is_running", lambda: True)
    monkeypatch.setattr(dmn, "_monitored_freshness", lambda ctx: (0, None))
    monkeypatch.setattr(dmn, "_poll_log_age_seconds", lambda ctx: None)
    r = _by_id(dmn.daemon_checks(_ctx(tmp_path)), "daemon.polling_fresh")
    assert r.severity == Severity.INFO


def test_polling_fresh_db_fresh_but_log_stale_warns(tmp_path, monkeypatch):
    # §6 cross-check: DB rows fresh, but the poll log hasn't advanced → warn.
    monkeypatch.setattr(dmn, "_is_running", lambda: True)
    monkeypatch.setattr(dmn, "_monitored_freshness", lambda ctx: (1, 5.0))
    monkeypatch.setattr(dmn, "_poll_log_age_seconds", lambda ctx: 600.0)
    r = _by_id(dmn.daemon_checks(_ctx(tmp_path)), "daemon.polling_fresh")
    assert r.severity == Severity.WARN


def test_newest_poll_log_uses_mtime_not_name(tmp_path):
    import os
    logs = tmp_path / "logs"; logs.mkdir()
    older = logs / "poll-v0.12.4-20260101-000000.log"; older.write_text("x")
    newer = logs / "poll-v0.9.0-20260102-000000.log"; newer.write_text("x")
    os.utime(older, (1000, 1000))   # older mtime, lexically LARGER version
    os.utime(newer, (2000, 2000))   # newer mtime, lexically SMALLER version
    assert dmn._newest_poll_log_version(_ctx(tmp_path)) == "0.9.0"  # mtime wins


def test_polling_fresh_no_monitored_but_log_stale_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(dmn, "_is_running", lambda: True)
    monkeypatch.setattr(dmn, "_monitored_freshness", lambda ctx: (0, None))
    monkeypatch.setattr(dmn, "_poll_log_age_seconds", lambda ctx: 600.0)
    r = _by_id(dmn.daemon_checks(_ctx(tmp_path)), "daemon.polling_fresh")
    assert r.severity == Severity.WARN


def test_plist_bad_args_critical(tmp_path, monkeypatch):
    import plistlib
    from pathlib import Path
    monkeypatch.setattr(dmn, "_is_running", lambda: True)
    monkeypatch.setattr(dmn, "_monitored_freshness", lambda ctx: (0, None))
    # autouse conftest sandboxes Path.home(); write the fake plist under it.
    la = Path.home() / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    (la / "com.polily.scheduler.dev.plist").write_bytes(plistlib.dumps({
        "ProgramArguments": ["py", "-m", "polily.cli", "scheduler", "run", "--config", "x"],
        "KeepAlive": True, "StandardErrorPath": "/tmp/e.log",
    }))
    r = _by_id(dmn.daemon_checks(_ctx(tmp_path)), "daemon.plist_valid")
    assert r.severity == Severity.CRITICAL  # legacy --config arg
