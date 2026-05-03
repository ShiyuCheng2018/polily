"""v0.11.0 Whis B1 — daemon plist WorkingDirectory + plist generation
caller use paths.data_dir(), NOT Path.cwd().

Strategy (chosen by implementer): scheduler.py extracts a helper
`_resolve_plist_working_dir()` so the 3 plist-generating callsites
delegate to one place. Tests assert on the helper directly. This avoids
mocking subprocess.run + filesystem + launchctl all at once.
"""
from __future__ import annotations

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily"))
    yield
    paths.set_data_dir_override(None)


def test_resolve_plist_working_dir_uses_paths_data_dir(monkeypatch, tmp_path):
    """The helper must compute working_dir from paths.data_dir(),
    regardless of cwd. Pre-fix behavior used Path.cwd() so a user running
    `polily scheduler register` from /tmp would get plist pointing at
    /tmp/data/."""
    # Force cwd somewhere completely different from POLILY_DATA_DIR
    wrong_cwd = tmp_path / "wrong_cwd"
    wrong_cwd.mkdir(exist_ok=True)
    monkeypatch.chdir(wrong_cwd)

    from polily.daemon.scheduler import _resolve_plist_working_dir
    result = _resolve_plist_working_dir()

    assert result == str(tmp_path / "polily")
    assert "wrong_cwd" not in result


def test_resolve_plist_working_dir_creates_directory(monkeypatch, tmp_path):
    """paths.data_dir() lazy-mkdirs on access — confirm the helper does
    not need callers to mkdir explicitly. Pre-fix code did
    `Path(working_dir, 'data').mkdir(...)` after `str(Path.cwd())`; that
    line should be unnecessary now."""
    target = tmp_path / "fresh"
    monkeypatch.setenv("POLILY_DATA_DIR", str(target))
    paths.set_data_dir_override(None)
    assert not target.exists()

    from polily.daemon.scheduler import _resolve_plist_working_dir
    _resolve_plist_working_dir()

    assert target.exists() and target.is_dir()
