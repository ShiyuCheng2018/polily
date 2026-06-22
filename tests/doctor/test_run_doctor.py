import io, json
from contextlib import redirect_stdout

import polily.doctor as doc
from polily.doctor.model import CheckResult, Severity


def test_run_doctor_json_exit_code(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(doc, "REGISTRY", [
        lambda ctx: CheckResult(id="x", title="X", severity=Severity.WARN, group="g"),
    ])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = doc.run_doctor(json=True)
    assert code == 1
    assert json.loads(buf.getvalue())["summary"]["exit_code"] == 1


def test_run_doctor_exit_zero_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(doc, "REGISTRY", [
        lambda ctx: CheckResult(id="x", title="X", severity=Severity.CRITICAL, group="g"),
    ])
    with redirect_stdout(io.StringIO()):
        assert doc.run_doctor(json=True, exit_zero=True) == 0


def test_run_doctor_check_exception_becomes_critical(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    def boom(ctx):
        raise ValueError("nope")
    monkeypatch.setattr(doc, "REGISTRY", [boom])
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = doc.run_doctor(json=True)
    assert code == 3
    payload = json.loads(buf.getvalue())
    assert payload["checks"][0]["id"].endswith(".errored")
    assert payload["checks"][0]["severity"] == "critical"
