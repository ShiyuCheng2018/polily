"""PyPI update-availability check — fetches latest stable version,
caches locally, persists user-dismissed-version state.

Used by TUI sidebar to render the "new content available" yellow `*`
on 更新日志 entry when a newer PyPI version is available than what
the user has acknowledged.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from packaging.version import InvalidVersion, Version

from polily.core import paths
from polily.core.config_store import load_all, upsert
from polily.core.db import PolilyDB

logger = logging.getLogger(__name__)

PYPI_JSON_URL = "https://pypi.org/pypi/polily/json"
CACHE_TTL = timedelta(hours=6)
CONFIG_KEY_DISMISSED = "update_check.last_dismissed_version"


def _cache_path() -> Path:
    return paths.data_dir() / ".update_cache.json"


def _read_cache() -> dict | None:
    p = _cache_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.debug("Update cache read failed: %s", e)
        return None


def _write_cache(latest_version: str) -> None:
    """Atomic write — POSIX `os.replace` is atomic on the same filesystem.
    Whis review fix: prevents JSONDecodeError if a concurrent reader
    hits the file mid-write."""
    p = _cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({
        "checked_at": datetime.now(UTC).isoformat(),
        "latest_version": latest_version,
    })
    # Write to temp file in same dir, then atomic rename
    with tempfile.NamedTemporaryFile(
        mode="w", dir=str(p.parent), delete=False, encoding="utf-8",
        prefix=".update_cache.", suffix=".tmp",
    ) as tf:
        tf.write(payload)
        tmp_path = tf.name
    os.replace(tmp_path, str(p))  # atomic on POSIX


def _is_cache_fresh(cache: dict) -> bool:
    try:
        checked_at = datetime.fromisoformat(cache["checked_at"])
        return datetime.now(UTC) - checked_at < CACHE_TTL
    except (KeyError, ValueError):
        return False


def fetch_latest_pypi_version(timeout: float = 5.0) -> str | None:
    """Fetch latest stable PyPI version. Returns None on any failure
    (network down, PyPI 5xx, malformed response). Never raises."""
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(PYPI_JSON_URL)
            r.raise_for_status()
            return r.json()["info"]["version"]
    except (httpx.HTTPError, KeyError, ValueError) as e:
        logger.debug("PyPI version fetch failed: %s", e)
        return None


def get_latest_version(force_refresh: bool = False) -> str | None:
    """Return cached latest version (refresh if cache stale or forced).
    None on persistent failure."""
    cache = _read_cache()
    if cache and not force_refresh and _is_cache_fresh(cache):
        return cache.get("latest_version")
    fresh = fetch_latest_pypi_version()
    if fresh:
        _write_cache(fresh)
        return fresh
    # Fetch failed but we have stale cache — return as fallback
    return cache.get("latest_version") if cache else None


def get_dismissed_version(db: PolilyDB) -> str | None:
    """Return version user last dismissed (None if never dismissed).
    Reads via canonical config_store.load_all.

    Whis review-2 fix: load_all() returns a FLAT dict
    `{key_path: deserialized_value}`, NOT a PolilyConfig instance.
    Access via dotted key, not attribute traversal.

    Empty string (the Pydantic default) is treated as "never dismissed"
    — matches behaviour of None.
    """
    cfg = load_all(db)
    raw = cfg.get(CONFIG_KEY_DISMISSED)
    return raw if raw else None


def set_dismissed_version(db: PolilyDB, version: str) -> None:
    """Persist via canonical config_store.upsert. Whis review fix:
    avoid raw SQL — config table schema is (key_path, value, updated_at)
    with NOT NULL on updated_at, and goes through validation."""
    upsert(db, CONFIG_KEY_DISMISSED, version)


def should_show_update_star(db: PolilyDB, force_refresh: bool = False) -> bool:
    """True iff a newer PyPI version than current is available AND user
    hasn't dismissed it."""
    from polily import __version__ as current_version

    latest = get_latest_version(force_refresh=force_refresh)
    if not latest:
        return False
    dismissed = get_dismissed_version(db) or "0.0.0"

    try:
        return (
            Version(latest) > Version(current_version)
            and Version(latest) > Version(dismissed)
        )
    except InvalidVersion:
        # Dev versions or bad data → no star
        return False
