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


def test_doctor_reports_daemon_claude_path_from_plist(
    tmp_path, monkeypatch, capsys
):
    """`polily doctor` must show what claude path the daemon will see,
    parsed from the installed plist. Lets the user one-command verify
    the v0.9.1 fix landed on their box."""
    import plistlib

    from polily import doctor as doctor_mod

    fake_plist = tmp_path / "com.polily.scheduler.plist"
    fake_plist.write_bytes(plistlib.dumps({
        "Label": "com.polily.scheduler",
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "POLILY_CLAUDE_CLI": "/Users/x/.nvm/versions/node/v20.19.6/bin/claude",
        },
    }))
    monkeypatch.setattr(doctor_mod, "PLIST_PATH", fake_plist)

    from rich.console import Console
    console = Console(force_terminal=False, width=120)
    doctor_mod._section_claude_cli(console)
    captured = capsys.readouterr().out

    assert "daemon" in captured.lower()
    assert "/Users/x/.nvm/versions/node/v20.19.6/bin/claude" in captured


def test_doctor_warns_when_plist_missing_claude_cli_var(
    tmp_path, monkeypatch, capsys
):
    """If the on-disk plist lacks POLILY_CLAUDE_CLI (stale plist from
    pre-v0.9.1), doctor should say so — tells the user to re-run
    `polily scheduler restart` to pick up the v0.9.1 fix."""
    import plistlib

    from polily import doctor as doctor_mod

    fake_plist = tmp_path / "com.polily.scheduler.plist"
    fake_plist.write_bytes(plistlib.dumps({
        "Label": "com.polily.scheduler",
        "EnvironmentVariables": {"PATH": "/usr/local/bin:/usr/bin:/bin"},
    }))
    monkeypatch.setattr(doctor_mod, "PLIST_PATH", fake_plist)

    from rich.console import Console
    console = Console(force_terminal=False, width=120)
    doctor_mod._section_claude_cli(console)
    captured = capsys.readouterr().out

    assert "scheduler restart" in captured


def test_doctor_plist_path_matches_scheduler_plist_path():
    """polily/doctor.py duplicates PLIST_PATH to keep its import graph
    light. Guarantee the two definitions stay in sync — if this test
    fails, update both or centralize the constant in a light module."""
    from polily import doctor as doctor_mod
    from polily.daemon import scheduler as sched_mod
    assert doctor_mod.PLIST_PATH == sched_mod.PLIST_PATH
