"""v0.11.0 Whis-review S3 — daemon poll log path resolves via paths
module, not via ``Path(__file__).resolve().parent.parent.parent``.

Pre-fix code did:

    project_root = Path(__file__).resolve().parent.parent.parent
    log_dir = project_root / "data" / "logs"

Under pipx install, ``Path(__file__)`` resolves to a path inside
``site-packages`` — read-only on most systems. Daemon would crash on
the first poll cycle when it tried to create the log file.

Post-fix: ``paths.log_dir() / 'scheduler.log'`` (or per-restart
``poll-v<ver>-<ts>.log``), independent of where the polily package is
installed.
"""
from __future__ import annotations

import pytest

from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Per-test env isolation: clear CLI override, pin POLILY_DATA_DIR,
    restore on teardown."""
    paths.set_data_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily"))
    yield
    paths.set_data_dir_override(None)


def test_poll_log_path_uses_paths_log_dir(tmp_path):
    """``_build_poll_log_path()`` lives under ``paths.log_dir()``."""
    from polily.daemon.poll_job import _build_poll_log_path

    result = _build_poll_log_path()
    expected_dir = tmp_path / "polily" / "logs"
    # Path is a poll log under the resolved log_dir; filename includes
    # version + timestamp so we can't assert on the exact name.
    assert result.parent == expected_dir, (
        f"poll log not under expected log_dir: {result} (expected parent "
        f"{expected_dir})"
    )


def test_poll_log_path_independent_of_dunder_file():
    """Pre-fix used ``Path(__file__).resolve().parent.parent.parent`` —
    post-fix must NOT leak the polily install location into the log
    path. Catches a regression where someone reverts to __file__ traversal.
    """
    from polily.daemon.poll_job import _build_poll_log_path

    result = _build_poll_log_path()
    bad_markers = ["site-packages", ".venv", "/usr/local/lib", "lib/python"]
    leaked = [m for m in bad_markers if m in str(result)]
    assert not leaked, (
        f"poll log path leaks installation location: {result} "
        f"(matched markers: {leaked})"
    )
