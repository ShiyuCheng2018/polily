import polily.doctor.checks.environment as env
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx(tmp_path, platform="darwin"):
    return DoctorContext(data_dir=tmp_path, db_path=tmp_path / "polily.db",
                         log_dir=tmp_path / "logs", data_dir_tier="env",
                         launchd_label="com.polily.scheduler", platform=platform)


def _by_id(results, cid):
    return next(r for r in results if r.id == cid)


def test_data_dir_writable_ok(tmp_path):
    r = _by_id(env.environment_checks(_ctx(tmp_path)), "env.data_dir_writable")
    assert r.severity == Severity.OK


def test_data_dir_not_writable_critical(tmp_path, monkeypatch):
    monkeypatch.setattr("os.access", lambda *a, **k: False)
    r = _by_id(env.environment_checks(_ctx(tmp_path)), "env.data_dir_writable")
    assert r.severity == Severity.CRITICAL


def test_nerd_font_is_not_verifiable(tmp_path):
    r = _by_id(env.environment_checks(_ctx(tmp_path)), "env.nerd_font")
    assert r.verifiable is False
    assert r.severity == Severity.INFO


def test_python_ok_helper():
    # Test the pure helper with injected tuples — no monkeypatching sys.version_info.
    assert env._python_ok((3, 10, 0), ">=3.11")[0] is False
    assert env._python_ok((3, 11, 5), ">=3.11")[0] is True
    assert env._python_ok((3, 13, 0), ">=3.11")[0] is True
