"""get_daemon_pid() parses launchctl list output into PID or None."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from polily.daemon.launchctl_query import get_daemon_pid, is_daemon_running


def _mock_run(*, stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.stderr = stderr
    r.returncode = returncode
    return r


def test_returns_pid_when_running():
    running_output = """{
    "Label" = "com.polily.scheduler";
    "OnDemand" = true;
    "LastExitStatus" = 0;
    "PID" = 43384;
    "Program" = "/path/to/python";
};
"""
    with patch("polily.daemon.launchctl_query.subprocess.run",
               return_value=_mock_run(stdout=running_output, returncode=0)):
        assert get_daemon_pid() == 43384
        assert is_daemon_running() is True


def test_returns_none_when_registered_but_not_running():
    # launchctl dict present but no "PID" line — means registered, last exited
    not_running_output = """{
    "Label" = "com.polily.scheduler";
    "OnDemand" = true;
    "LastExitStatus" = 0;
};
"""
    with patch("polily.daemon.launchctl_query.subprocess.run",
               return_value=_mock_run(stdout=not_running_output, returncode=0)):
        assert get_daemon_pid() is None
        assert is_daemon_running() is False


def test_returns_none_when_not_registered():
    with patch("polily.daemon.launchctl_query.subprocess.run",
               return_value=_mock_run(
                   stderr="Could not find service ...",
                   returncode=113,
               )):
        assert get_daemon_pid() is None
        assert is_daemon_running() is False


def test_returns_none_on_launchctl_timeout():
    import subprocess
    with patch("polily.daemon.launchctl_query.subprocess.run",
               side_effect=subprocess.TimeoutExpired(cmd="launchctl", timeout=2)):
        assert get_daemon_pid() is None


def test_returns_none_when_launchctl_binary_missing():
    with patch("polily.daemon.launchctl_query.subprocess.run",
               side_effect=FileNotFoundError("launchctl: command not found")):
        assert get_daemon_pid() is None


def test_kill_daemon_success():
    from polily.daemon.launchctl_query import kill_daemon
    with patch("polily.daemon.launchctl_query.subprocess.run",
               return_value=_mock_run(returncode=0)) as mock_run:
        assert kill_daemon("TERM") is True
        args = mock_run.call_args.args[0]
        assert args[0:3] == ["launchctl", "kill", "TERM"]
        assert args[3].startswith("gui/") and args[3].endswith("com.polily.scheduler")


def test_kill_daemon_not_registered():
    from polily.daemon.launchctl_query import kill_daemon
    with patch("polily.daemon.launchctl_query.subprocess.run",
               return_value=_mock_run(returncode=113)):
        assert kill_daemon("TERM") is False


def test_kill_daemon_tolerates_subprocess_errors():
    import subprocess as sp_mod

    from polily.daemon.launchctl_query import kill_daemon
    for exc in [sp_mod.TimeoutExpired(cmd="launchctl", timeout=2),
                FileNotFoundError("launchctl: command not found"),
                OSError("generic")]:
        with patch("polily.daemon.launchctl_query.subprocess.run", side_effect=exc):
            assert kill_daemon("TERM") is False
