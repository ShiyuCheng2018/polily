# tests/test_cli_doctor.py
"""v0.8.0 Task 13: `polily doctor` subcommand."""
from typer.testing import CliRunner

from polily.cli import app

runner = CliRunner()


def test_doctor_subcommand_exists():
    result = runner.invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout.lower() or "diagnostic" in result.stdout.lower()


def test_doctor_prints_font_section():
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    # Must show sample Nerd Font characters for visual confirmation
    assert "\uf073" in result.stdout or "Nerd Font" in result.stdout


def test_doctor_prints_terminal_size():
    result = runner.invoke(app, ["doctor"])
    assert "终端尺寸" in result.stdout or "terminal" in result.stdout.lower()


def test_doctor_prints_install_instructions():
    result = runner.invoke(app, ["doctor"])
    assert "brew install" in result.stdout or "font-jetbrains-mono-nerd-font" in result.stdout
