"""Tests for scheduler daemon + launchd plist generation."""

import plistlib
import sys

from polily.daemon.scheduler import generate_launchd_plist


def test_generate_plist_structure():
    plist_bytes = generate_launchd_plist(
        python_path="/usr/bin/python3",
        working_dir="/path/to/polily",
    )
    plist = plistlib.loads(plist_bytes)
    assert plist["Label"] == "com.polily.scheduler"
    assert "KeepAlive" in plist
    assert plist["KeepAlive"]["SuccessfulExit"] is False
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
