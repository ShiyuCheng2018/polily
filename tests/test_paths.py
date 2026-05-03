"""v0.11.0 — paths module: 3-layer resolution (CLI flag > env var > platformdirs).

The resolver is module-level state on `polily.core.paths`. Tests
isolate via monkeypatch.delenv + paths.set_data_dir_override(None) +
paths.set_log_dir_override(None) in a fixture so cross-test bleed is
impossible.
"""
from __future__ import annotations

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate_paths_state(monkeypatch):
    """Wipe all path env vars and overrides before/after each test."""
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    yield
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


def test_data_dir_default_is_platformdirs(monkeypatch, tmp_path):
    """No env, no override → platformdirs.user_data_dir('polily')."""
    # Force platformdirs to return a deterministic path so we can assert
    # without depending on the test runner's actual home.
    import platformdirs
    monkeypatch.setattr(
        platformdirs, "user_data_dir",
        lambda app, appauthor=False: str(tmp_path / "appdata" / app),
    )
    assert paths.data_dir() == tmp_path / "appdata" / "polily"


def test_data_dir_env_var_overrides_default(monkeypatch, tmp_path):
    custom = tmp_path / "custom_data"
    monkeypatch.setenv("POLILY_DATA_DIR", str(custom))
    assert paths.data_dir() == custom


def test_data_dir_cli_override_beats_env(monkeypatch, tmp_path):
    """CLI flag (set via paths.set_data_dir_override) wins over env."""
    cli_path = tmp_path / "cli_path"
    env_path = tmp_path / "env_path"
    monkeypatch.setenv("POLILY_DATA_DIR", str(env_path))
    paths.set_data_dir_override(cli_path)
    assert paths.data_dir() == cli_path


def test_data_dir_creates_directory_lazily(tmp_path, monkeypatch):
    target = tmp_path / "lazy" / "polily_data"
    monkeypatch.setenv("POLILY_DATA_DIR", str(target))
    assert not target.exists()
    result = paths.data_dir()
    assert result.is_dir()


def test_data_dir_idempotent_mkdir(tmp_path, monkeypatch):
    """Calling data_dir twice doesn't raise on existing dir."""
    target = tmp_path / "exists"
    target.mkdir()
    monkeypatch.setenv("POLILY_DATA_DIR", str(target))
    assert paths.data_dir() == target
    assert paths.data_dir() == target  # second call doesn't raise


def test_db_path_is_data_dir_slash_polily_db(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    assert paths.db_path() == tmp_path / "polily.db"


def test_log_dir_default_is_data_dir_slash_logs(monkeypatch, tmp_path):
    """When POLILY_LOG_DIR unset, log_dir = data_dir / 'logs'."""
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    assert paths.log_dir() == tmp_path / "logs"


def test_log_dir_env_var_overrides_default(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("POLILY_LOG_DIR", str(tmp_path / "logs"))
    assert paths.log_dir() == tmp_path / "logs"


def test_log_dir_cli_override_beats_env(monkeypatch, tmp_path):
    cli_log = tmp_path / "cli_logs"
    env_log = tmp_path / "env_logs"
    monkeypatch.setenv("POLILY_LOG_DIR", str(env_log))
    paths.set_log_dir_override(cli_log)
    assert paths.log_dir() == cli_log


def test_agent_feedback_log_path(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    assert paths.agent_feedback_log() == tmp_path / "logs" / "agent_feedback.log"


def test_agent_debug_log_path(monkeypatch, tmp_path):
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    assert paths.agent_debug_log() == tmp_path / "logs" / "agent_debug.log"


def test_launchd_label_default(monkeypatch):
    monkeypatch.delenv("POLILY_LAUNCHD_LABEL", raising=False)
    assert paths.launchd_label() == "com.polily.scheduler"


def test_launchd_label_env_override(monkeypatch):
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")
    assert paths.launchd_label() == "com.polily.scheduler.dev"


def test_launchd_plist_path_uses_label(monkeypatch):
    monkeypatch.setenv("POLILY_LAUNCHD_LABEL", "com.polily.scheduler.dev")
    p = paths.launchd_plist_path()
    assert p.name == "com.polily.scheduler.dev.plist"
    assert "Library/LaunchAgents" in str(p)


def test_set_data_dir_override_accepts_str(tmp_path):
    """set_data_dir_override accepts both Path and str for ergonomics."""
    paths.set_data_dir_override(str(tmp_path))
    assert paths.data_dir() == tmp_path


def test_legacy_data_dir_resolves_to_repo_data(monkeypatch, tmp_path):
    """legacy_data_dir() always points at './data' relative to cwd, NOT to
    the resolver. Used only by first-launch migration to find pre-v0.11.0
    data."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "polily.db").write_text("")
    assert paths.legacy_data_dir() == tmp_path / "data"
    assert paths.legacy_db_path() == tmp_path / "data" / "polily.db"
