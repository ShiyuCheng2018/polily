"""Tests for scheduler daemon + launchd plist generation."""

import plistlib
import sys

import pytest

from polily.daemon.scheduler import generate_launchd_plist


@pytest.fixture(autouse=True)
def _neutralize_which(monkeypatch):
    """Force `shutil.which('claude')` to return None in scheduler plist
    tests. Individual tests that need a resolved path pass
    `claude_cli="/explicit/path"` to `generate_launchd_plist` instead.

    Rationale: without this, tests embed the dev's actual nvm path in
    generated plist bytes, coupling CI behavior to local install state.

    Patches via string `"shutil.which"` (not `sched.shutil.which`) so
    it's robust to whether scheduler.py imports shutil at module level
    or via `from shutil import which`.
    """
    monkeypatch.setattr("shutil.which", lambda *_a, **_kw: None)


def test_generate_plist_structure():
    plist_bytes = generate_launchd_plist(
        python_path="/usr/bin/python3",
        working_dir="/path/to/polily",
    )
    plist = plistlib.loads(plist_bytes)
    assert plist["Label"] == "com.polily.scheduler"
    assert "KeepAlive" in plist
    # v0.11.3: KeepAlive set to boolean True (always keep alive). v0.11.2's
    # {Crashed: True} broke initial launch under launchd. See
    # tests/test_daemon_plist_v0_11_2.py::test_plist_keepalive_is_unconditional_true
    # for the detailed semantic explanation.
    assert plist["KeepAlive"] is True
    assert plist["WorkingDirectory"] == "/path/to/polily"


def test_generate_plist_program_args():
    plist_bytes = generate_launchd_plist(
        python_path="/opt/venv/bin/python",
        working_dir="/home/user/polily",
    )
    plist = plistlib.loads(plist_bytes)
    args = plist["ProgramArguments"]
    assert args[0] == "/opt/venv/bin/python"
    assert "-m" in args
    assert "polily.cli" in args


def test_generate_plist_log_paths():
    plist_bytes = generate_launchd_plist(
        python_path="/usr/bin/python3",
        working_dir="/path/to/polily",
    )
    plist = plistlib.loads(plist_bytes)
    assert "StandardOutPath" in plist
    assert "StandardErrorPath" in plist
    assert plist["StandardOutPath"] == "/dev/null"


def test_plist_uses_current_python():
    """generate_launchd_plist with default python_path should use sys.executable."""
    plist_bytes = generate_launchd_plist(working_dir="/tmp/test")
    plist = plistlib.loads(plist_bytes)
    assert plist["ProgramArguments"][0] == sys.executable


def test_sweep_legacy_pid_file_removes_stale_file(tmp_path, monkeypatch):
    """v0.9.0: launchctl replaced the PID file. _sweep_legacy_pid_file()
    must delete any lingering file from a pre-v0.9.0 install on daemon
    startup — this is the sole migration mechanism for existing users.

    v0.11.0: target file moved from `./data/scheduler.pid` (cwd-relative)
    to `<paths.data_dir>/scheduler.pid`. The sweep resolves via
    `paths.data_dir()` so POLILY_DATA_DIR redirection isolates the test
    from real install state.
    """
    from polily.core import paths
    from polily.daemon.scheduler import _sweep_legacy_pid_file

    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily"))
    paths.set_data_dir_override(None)
    stale = tmp_path / "polily" / "scheduler.pid"
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("12345")
    assert stale.exists()  # setup sanity

    _sweep_legacy_pid_file()

    assert not stale.exists(), "stale PID file must be swept on daemon start"


def test_sweep_legacy_pid_file_noop_when_absent(tmp_path, monkeypatch):
    """Safe no-op when the file doesn't exist (fresh v0.9.0 install).

    v0.11.0: redirect via POLILY_DATA_DIR so paths.data_dir() resolves
    under tmp_path, not the real install.
    """
    from polily.core import paths
    from polily.daemon.scheduler import _sweep_legacy_pid_file

    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily"))
    paths.set_data_dir_override(None)
    # No scheduler.pid file exists — sweep should not crash.
    _sweep_legacy_pid_file()  # should not raise
