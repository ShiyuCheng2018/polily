"""v0.11.0 — agent_debug.log (and agent_feedback.log) write to
paths.log_dir(), not os.getcwd()/data/logs.

Whis-review v2 NI2: only path-resolution invariant tests live here.
End-to-end via _dump_debug was dropped as fragile (importlib.reload
to undo conftest's autouse _suppress_agent_debug_log adds reload-
after-monkeypatch hazards for marginal value — the path equality
assertions below already catch any regression that re-pins the
debug log to a cwd-derived path).
"""
from __future__ import annotations

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily_data"))
    yield
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


def test_agent_debug_log_path_resolves_via_paths_module(monkeypatch, tmp_path):
    """paths.agent_debug_log() returns paths.log_dir() / 'agent_debug.log',
    NOT cwd-relative. This is the primary invariant — testing this directly
    avoids the conftest autouse _suppress_agent_debug_log fixture
    interaction."""
    expected = tmp_path / "polily_data" / "logs" / "agent_debug.log"
    assert paths.agent_debug_log() == expected


def test_agent_debug_log_dir_is_independent_of_cwd(monkeypatch, tmp_path):
    """Pre-fix bug: import-time _DEBUG_DIR captured cwd at module load.
    Post-fix: paths.log_dir() resolves at call time, ignoring cwd."""
    (tmp_path / "wrong_cwd").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "wrong_cwd")

    # Even after chdir, paths.agent_debug_log() should still resolve via env.
    expected = tmp_path / "polily_data" / "logs" / "agent_debug.log"
    assert paths.agent_debug_log() == expected
    # And the cwd-relative path should NOT be where it points.
    cwd_log = tmp_path / "wrong_cwd" / "data" / "logs" / "agent_debug.log"
    assert paths.agent_debug_log() != cwd_log
