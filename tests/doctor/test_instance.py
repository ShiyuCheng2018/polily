from pathlib import Path
import polily.doctor.checks.instance as inst
from polily.doctor.context import DoctorContext
from polily.doctor.model import Severity


def _ctx(tmp_path, tier="env", label="com.polily.scheduler.dev"):
    return DoctorContext(
        data_dir=tmp_path / "data", db_path=tmp_path / "data" / "polily.db",
        log_dir=tmp_path / "data" / "logs", data_dir_tier=tier,
        launchd_label=label, platform="darwin",
    )


def _by_id(results, cid):
    return next(r for r in results if r.id == cid)


def test_dev_checkout_but_prod_data_is_critical(tmp_path, monkeypatch):
    # cwd looks like a polily source checkout, but data resolved to default (prod)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "polily"\n')
    monkeypatch.chdir(tmp_path)
    ctx = _ctx(tmp_path, tier="default", label="com.polily.scheduler")
    results = inst.instance_checks(ctx)
    r = _by_id(results, "instance.dev_checkout_prod_data")
    assert r.severity == Severity.CRITICAL


def test_clean_dev_no_trap(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "polily"\n')
    monkeypatch.chdir(tmp_path)
    ctx = _ctx(tmp_path, tier="env", label="com.polily.scheduler.dev")
    results = inst.instance_checks(ctx)
    assert _by_id(results, "instance.dev_checkout_prod_data").severity == Severity.OK


def test_resolution_always_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx = _ctx(tmp_path)
    r = _by_id(inst.instance_checks(ctx), "instance.resolution")
    assert r.severity == Severity.INFO
    assert r.value["data_dir"].endswith("data")


def test_daemon_data_dir_mismatch_critical(tmp_path, monkeypatch):
    import plistlib
    from pathlib import Path
    monkeypatch.chdir(tmp_path)
    # autouse conftest sandboxes Path.home(); write a fake plist whose data dir
    # differs from ctx.data_dir → the daemon writes a DIFFERENT db than doctor reads.
    la = Path.home() / "Library" / "LaunchAgents"
    la.mkdir(parents=True, exist_ok=True)
    (la / "com.polily.scheduler.dev.plist").write_bytes(plistlib.dumps(
        {"EnvironmentVariables": {"POLILY_DATA_DIR": "/somewhere/else"}}))
    r = _by_id(inst.instance_checks(_ctx(tmp_path)), "instance.daemon_data_dir_match")
    assert r.severity == Severity.CRITICAL
