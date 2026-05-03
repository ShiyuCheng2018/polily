"""v0.11.0 — launchd plist: WorkingDirectory + EnvironmentVariables
propagate paths overrides. Label is env-overridable so dev daemon
runs alongside prod under com.polily.scheduler.dev."""
from __future__ import annotations

import plistlib

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    monkeypatch.delenv("POLILY_LAUNCHD_LABEL", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    yield
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


def test_plist_working_directory_is_paths_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))

    from polily.daemon.scheduler import generate_launchd_plist
    plist_bytes = generate_launchd_plist(working_dir=str(paths.data_dir()))
    parsed = plistlib.loads(plist_bytes)
    assert parsed["WorkingDirectory"] == str(tmp_path / "data")


def test_plist_propagates_polily_data_dir_env(monkeypatch, tmp_path):
    """EnvironmentVariables block contains POLILY_DATA_DIR so launchctl-
    spawned daemon agrees with the parent process about path resolution."""
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))

    from polily.daemon.scheduler import generate_launchd_plist
    plist_bytes = generate_launchd_plist(working_dir=str(paths.data_dir()))
    parsed = plistlib.loads(plist_bytes)
    env = parsed.get("EnvironmentVariables", {})
    assert env.get("POLILY_DATA_DIR") == str(tmp_path / "data")


def test_plist_propagates_polily_log_dir_env_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POLILY_LOG_DIR", str(tmp_path / "logs"))

    from polily.daemon.scheduler import generate_launchd_plist
    plist_bytes = generate_launchd_plist(working_dir=str(paths.data_dir()))
    parsed = plistlib.loads(plist_bytes)
    env = parsed.get("EnvironmentVariables", {})
    assert env.get("POLILY_LOG_DIR") == str(tmp_path / "logs")


def test_plist_omits_log_dir_env_when_default(monkeypatch, tmp_path):
    """If POLILY_LOG_DIR is unset (default = data_dir/logs), no need to
    propagate it — daemon will compute the same default."""
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))

    from polily.daemon.scheduler import generate_launchd_plist
    plist_bytes = generate_launchd_plist(working_dir=str(paths.data_dir()))
    parsed = plistlib.loads(plist_bytes)
    env = parsed.get("EnvironmentVariables", {})
    assert "POLILY_LOG_DIR" not in env


def test_plist_label_uses_paths_launchd_label(monkeypatch):
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")

    from polily.daemon.scheduler import generate_launchd_plist
    plist_bytes = generate_launchd_plist(working_dir="/tmp")
    parsed = plistlib.loads(plist_bytes)
    assert parsed["Label"] == "com.polily.scheduler.dev"


def test_launchctl_query_label_uses_env_override(monkeypatch):
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")
    # The live `_label()` helper must read the env each call, so a
    # mid-session env change must reflect.
    from polily.daemon import launchctl_query
    assert launchctl_query._label() == "com.polily.scheduler.dev"


def test_legacy_pid_sweep_uses_paths_data_dir(monkeypatch, tmp_path):
    """v0.11.0 — sweep '<paths.data_dir>/scheduler.pid' (the actual
    location of pre-v0.9.0 pid files when the daemon ran under
    paths.data_dir as cwd) instead of './data/scheduler.pid'."""
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))
    legacy_pid = tmp_path / "data" / "scheduler.pid"
    legacy_pid.parent.mkdir(parents=True, exist_ok=True)
    legacy_pid.write_text("12345\n")

    from polily.daemon.scheduler import _sweep_legacy_pid_file
    _sweep_legacy_pid_file()
    assert not legacy_pid.exists(), "legacy pid file should have been swept"


def test_all_plist_label_usages_are_live(monkeypatch):
    """Whis-review B2: changing POLILY_LAUNCHD_LABEL mid-session must
    affect what plist sites actually write. Snapshot constant remains
    for backward compat but live sites use the helper."""
    from polily.daemon import scheduler

    # Initial label
    monkeypatch.delenv("POLILY_LAUNCHD_LABEL", raising=False)
    paths.set_data_dir_override(None)
    initial_label = scheduler._plist_label()
    assert initial_label == "com.polily.scheduler"

    # Override env
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")
    new_label = scheduler._plist_label()
    assert new_label == "com.polily.scheduler.dev"

    # Plist generation respects the new label
    plist_bytes = scheduler.generate_launchd_plist(working_dir="/tmp")
    parsed = plistlib.loads(plist_bytes)
    assert parsed["Label"] == "com.polily.scheduler.dev"


def test_plist_path_helper_resolves_via_paths_module(monkeypatch, tmp_path):
    """B2: scheduler.py + doctor.py expose `_plist_path()` that consults
    paths.launchd_plist_path() at call time, so a POLILY_LAUNCHD_LABEL
    flip mid-session redirects file IO to the dev plist."""
    from pathlib import Path

    from polily.daemon import scheduler
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    expected = tmp_path / "Library" / "LaunchAgents" / "com.polily.scheduler.dev.plist"
    assert scheduler._plist_path() == expected
