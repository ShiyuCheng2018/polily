import io
import json
from contextlib import redirect_stdout

from polily.doctor.context import DoctorContext
from polily.doctor.model import CheckResult, Severity
from polily.doctor.render import render_human, render_json


def _ctx(tmp_path):
    return DoctorContext(
        data_dir=tmp_path, db_path=tmp_path / "polily.db", log_dir=tmp_path / "logs",
        data_dir_tier="env", launchd_label="com.polily.scheduler.dev", platform="darwin",
    )


def _results():
    return [
        CheckResult(id="a", title="A", severity=Severity.OK, group="g1"),
        CheckResult(id="b", title="B", severity=Severity.WARN, detail="d",
                    fix_hint="fix b", group="g2"),
    ]


def test_render_json_is_pure_json(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_json("0.12.4", _ctx(tmp_path), _results())
    payload = json.loads(buf.getvalue())  # must parse — stdout is ONLY json
    assert payload["polily_version"] == "0.12.4"
    assert payload["instance"]["role"] == "dev"
    assert payload["summary"] == {"ok": 1, "info": 0, "warn": 1,
                                  "critical": 0, "skipped": 0, "exit_code": 1}
    ids = [c["id"] for c in payload["checks"]]
    assert ids == ["a", "b"]


def test_render_human_contains_titles_and_fix(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        render_human("0.12.4", _ctx(tmp_path), _results())
    out = buf.getvalue()
    assert "A" in out and "B" in out
    assert "fix b" in out
