"""Tests for update_check module — PyPI fetch, cache, dismissed state."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta


def test_should_show_star_when_pypi_newer_and_not_dismissed(
    polily_db, monkeypatch, tmp_path,
):
    """Star shows: PyPI > current AND PyPI > dismissed."""
    from polily.core import paths, update_check

    paths.set_data_dir_override(tmp_path)
    update_check._write_cache("0.99.0")
    monkeypatch.setattr(update_check, "_is_cache_fresh", lambda c: True)
    monkeypatch.setattr("polily.__version__", "0.11.4")

    assert update_check.should_show_update_star(polily_db) is True


def test_does_not_show_when_user_dismissed_current_latest(
    polily_db, monkeypatch, tmp_path,
):
    """User clicked 更新日志 for v0.99.0 → no star until v0.99.1+ comes out."""
    from polily.core import paths, update_check

    paths.set_data_dir_override(tmp_path)
    update_check._write_cache("0.99.0")
    monkeypatch.setattr(update_check, "_is_cache_fresh", lambda c: True)
    monkeypatch.setattr("polily.__version__", "0.11.4")
    update_check.set_dismissed_version(polily_db, "0.99.0")

    assert update_check.should_show_update_star(polily_db) is False


def test_shows_again_when_newer_release_after_dismiss(
    polily_db, monkeypatch, tmp_path,
):
    """User dismissed 0.99.0, then 0.99.1 is released → star shows again."""
    from polily.core import paths, update_check

    paths.set_data_dir_override(tmp_path)
    update_check.set_dismissed_version(polily_db, "0.99.0")
    update_check._write_cache("0.99.1")  # newer than dismissed
    monkeypatch.setattr(update_check, "_is_cache_fresh", lambda c: True)
    monkeypatch.setattr("polily.__version__", "0.11.4")

    assert update_check.should_show_update_star(polily_db) is True


def test_pypi_fetch_failure_is_silent(polily_db, monkeypatch, tmp_path):
    """Network down → no star, no exception."""
    from polily.core import paths, update_check

    paths.set_data_dir_override(tmp_path)
    monkeypatch.setattr(
        update_check, "fetch_latest_pypi_version", lambda timeout=5.0: None,
    )

    # Cache empty + fetch returns None → no star, no raise
    assert update_check.should_show_update_star(polily_db, force_refresh=True) is False


def test_cache_ttl_6h(monkeypatch, tmp_path):
    """Cache older than 6h is stale; fresh write resets timer."""
    from polily.core import paths, update_check

    paths.set_data_dir_override(tmp_path)
    update_check._write_cache("0.99.0")
    cache = update_check._read_cache()
    assert update_check._is_cache_fresh(cache)

    # Manually rewind checked_at by 7 hours
    cache["checked_at"] = (datetime.now(UTC) - timedelta(hours=7)).isoformat()
    update_check._cache_path().write_text(
        json.dumps(cache), encoding="utf-8",
    )
    cache2 = update_check._read_cache()
    assert not update_check._is_cache_fresh(cache2)
