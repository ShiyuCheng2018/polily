# tests/test_cli_doctor.py
"""`polily doctor` CLI contract: flags, exit codes, JSON shape."""
import json
from typer.testing import CliRunner
from polily.cli import app

runner = CliRunner()


def test_doctor_json_is_valid_and_has_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")
    result = runner.invoke(app, ["doctor", "--json", "--offline"])
    payload = json.loads(result.stdout)
    assert "summary" in payload and "checks" in payload
    assert payload["summary"]["exit_code"] == result.exit_code


def test_doctor_exit_zero_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["doctor", "--json", "--offline", "--exit-zero"])
    assert result.exit_code == 0


def test_doctor_human_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    result = runner.invoke(app, ["doctor", "--offline"])
    assert "Polily Doctor" in result.stdout
    assert result.exit_code in (0, 1, 3)
