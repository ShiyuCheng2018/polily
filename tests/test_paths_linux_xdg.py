"""v0.11.0 — verify paths resolver produces correct Linux defaults via
platformdirs.

v0.11.4 (OBS-2): split into two tests for cross-platform clarity.

- ``test_data_dir_uses_platformdirs_user_data_dir`` runs on every OS
  via a mocked ``platformdirs.user_data_dir``. Exercises the
  ``polily.core.paths.data_dir`` code path without depending on the
  host platform's real platformdirs behavior. This is the always-on
  regression guard.

- ``test_data_dir_uses_xdg_with_real_xdg_env_on_linux`` exercises the
  real platformdirs + real XDG_DATA_HOME path. Linux-only because
  platformdirs only honors XDG_DATA_HOME on Linux. Skipped on macOS /
  Windows. CI matrix's Linux runner picks it up as a real assertion;
  macOS dev box and macOS CI runner skip it (1 skipped is expected,
  not a regression).
"""
from __future__ import annotations

import platform

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    yield
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


def test_data_dir_uses_platformdirs_user_data_dir(monkeypatch, tmp_path):
    """When platformdirs simulates Linux behavior, data_dir should land
    under it. Mock-based so this runs on macOS dev boxes."""
    import platformdirs
    monkeypatch.setattr(
        platformdirs, "user_data_dir",
        lambda app, appauthor=False: str(tmp_path / ".local" / "share" / app),
    )
    result = paths.data_dir()
    assert result == tmp_path / ".local" / "share" / "polily"


def test_data_dir_uses_xdg_with_real_xdg_env_on_linux(monkeypatch, tmp_path):
    """Real platformdirs respect XDG_DATA_HOME on Linux. Skip on non-Linux."""
    if platform.system() != "Linux":
        pytest.skip("XDG_DATA_HOME only honored on Linux by platformdirs")

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg_data"))
    result = paths.data_dir()
    assert str(tmp_path / "xdg_data") in str(result), f"got {result}"
