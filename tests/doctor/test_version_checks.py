import polily.doctor.checks.version as vc
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx(tmp_path, offline=False):
    return DoctorContext(data_dir=tmp_path, db_path=tmp_path / "polily.db",
                         log_dir=tmp_path / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform="darwin", offline=offline)


def _by_id(rs, cid):
    return next(r for r in rs if r.id == cid)


def test_pypi_skipped_when_offline(tmp_path):
    r = _by_id(vc.version_checks(_ctx(tmp_path, offline=True)), "version.pypi_latest")
    assert r.severity == Severity.SKIPPED


def test_update_available_warns(tmp_path, monkeypatch):
    monkeypatch.setattr(vc, "_installed", lambda: "0.12.4")
    monkeypatch.setattr(vc, "_pypi_latest", lambda: "0.13.0")
    r = _by_id(vc.version_checks(_ctx(tmp_path)), "version.pypi_latest")
    assert r.severity == Severity.WARN


def test_up_to_date_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(vc, "_installed", lambda: "0.13.0")
    monkeypatch.setattr(vc, "_pypi_latest", lambda: "0.13.0")
    r = _by_id(vc.version_checks(_ctx(tmp_path)), "version.pypi_latest")
    assert r.severity == Severity.OK
