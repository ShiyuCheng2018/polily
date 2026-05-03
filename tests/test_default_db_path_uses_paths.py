"""v0.11.0 — default_db_path delegates to paths.db_path, ignoring the
informational archiving.db_file Pydantic default."""
from __future__ import annotations

import pytest

from polily.core import paths
from polily.core.config import default_db_path


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    paths.set_data_dir_override(None)
    yield
    paths.set_data_dir_override(None)


def test_default_db_path_uses_paths_resolver(monkeypatch, tmp_path):
    """When POLILY_DATA_DIR is set, default_db_path returns
    $POLILY_DATA_DIR/polily.db, NOT ./data/polily.db."""
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    result = default_db_path()
    assert result == tmp_path / "polily.db"
    assert "data/polily.db" not in str(result)


def test_default_db_path_respects_cli_override(tmp_path):
    paths.set_data_dir_override(tmp_path / "cli")
    result = default_db_path()
    assert result == tmp_path / "cli" / "polily.db"


def test_default_db_path_returns_absolute_path(monkeypatch, tmp_path):
    """Caller invariant: default_db_path always returns an absolute Path
    (callers like PolilyDB don't try to resolve relative-to-cwd)."""
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path))
    result = default_db_path()
    assert result.is_absolute(), f"expected absolute, got {result!r}"
