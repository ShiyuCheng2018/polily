"""Polily TUI i18n — runtime translation lookup with hotkey-driven language switching.

Public API:
    init_i18n(catalogs, default)   # call once at app startup
    t(key, **vars)                 # primary translation function
    set_language(lang)             # switch active language; raises ValueError on unknown
    current_language() -> str
    available_languages() -> list[str]

    load_catalogs(directory)       # loader — scans <directory>/*.json

Backward compat (existing callers):
    translate_status(status)       # delegates to t(f"status.{status}")
    translate_trigger(source)      # delegates to t(f"trigger.{source}")

Design notes:
- t() reads `_current_language` on every call (no caching). Switching language and
  triggering a re-compose is sufficient for views to display new strings.
- `_lock` is RLock; concurrency cost is negligible compared to TUI render rates.
- Missing keys fall back to: current → fallback ("zh") → key string itself + warning log.
  Raising would break TUI mid-migration; logging makes drift visible.

See docs/runtime-i18n-design.md §4.1 for the full design.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from polily.tui.i18n.loader import load_catalogs as _load_catalogs

logger = logging.getLogger(__name__)

_FALLBACK_LANG = "zh"
_BUNDLED_CATALOGS_DIR = Path(__file__).parent / "catalogs"

_lock = threading.RLock()
_current_language: str = _FALLBACK_LANG
_catalogs: dict[str, Mapping[str, str]] = {}
_auto_loaded: bool = False


def _ensure_bundled_loaded() -> None:
    """Lazy-load the package's own catalogs/*.json on first use.

    Lets `translate_status` and ad-hoc `t()` calls work without an explicit
    `init_i18n()` (e.g., in unit tests of individual views, or before app
    startup completes). Idempotent.

    `init_i18n()` overrides whatever was auto-loaded.
    """
    global _auto_loaded, _catalogs
    if _auto_loaded or _catalogs:
        return
    bundled = _load_catalogs(_BUNDLED_CATALOGS_DIR)
    if bundled:
        _catalogs = bundled
    _auto_loaded = True


def init_i18n(catalogs: Mapping[str, Mapping[str, str]], default: str) -> None:
    """Initialize the i18n module. Idempotent — safe to call multiple times.

    Args:
        catalogs: lang_code -> {key: translation} mapping.
        default: the language to start in. Falls back to FALLBACK_LANG if absent.
    """
    global _current_language, _catalogs, _auto_loaded
    with _lock:
        _catalogs = dict(catalogs)
        _auto_loaded = True  # explicit init wins over auto-load
        if default in _catalogs:
            _current_language = default
        elif _FALLBACK_LANG in _catalogs:
            _current_language = _FALLBACK_LANG
        else:
            # No catalogs at all (test mode or pre-init) — keep default;
            # t() will fallback to key strings.
            _current_language = default


def t(key: str, **vars: Any) -> str:
    """Translate `key` in the current language. Format with **vars (str.format).

    Lookup order: current language -> fallback (zh) -> key itself.
    """
    _ensure_bundled_loaded()
    with _lock:
        cat = _catalogs.get(_current_language)
        s: str | None = cat.get(key) if cat else None
        if s is None:
            fallback = _catalogs.get(_FALLBACK_LANG)
            s = fallback.get(key) if fallback else None
        if s is None:
            # Note logging.warning, not raising — keeps TUI usable mid-migration.
            logger.warning("i18n: missing key %r in lang=%s", key, _current_language)
            s = key
    if vars:
        try:
            return s.format(**vars)
        except (KeyError, IndexError) as e:
            logger.warning("i18n: format failed for key=%r vars=%r: %s", key, vars, e)
            return s
    return s


def set_language(lang: str) -> None:
    """Switch the active language. Raises ValueError if `lang` was not loaded."""
    global _current_language
    with _lock:
        if lang not in _catalogs:
            raise ValueError(f"unknown language: {lang!r} (loaded: {sorted(_catalogs)})")
        _current_language = lang


def current_language() -> str:
    with _lock:
        return _current_language


def available_languages() -> list[str]:
    with _lock:
        return sorted(_catalogs.keys())


# --- backward-compat shims for existing callers ---


def translate_status(status: str) -> str:
    """Translate a scan_logs.status enum value. Unknown → returned as-is.

    Mirrors the old polily.tui.i18n.translate_status contract: missing keys
    return the input verbatim (NOT the prefixed catalog key), so legacy
    callers see the same behavior they had before the package conversion.
    """
    if not status:
        return status
    translated = t(f"status.{status}")
    return status if translated == f"status.{status}" else translated


def translate_trigger(source: str) -> str:
    """Translate a scan_logs.trigger_source enum value. Unknown → returned as-is."""
    if not source:
        return source
    translated = t(f"trigger.{source}")
    return source if translated == f"trigger.{source}" else translated


# --- loader re-export ---


def load_catalogs(directory: Path) -> dict[str, dict[str, str]]:
    """Scan `directory/*.json`; return {lang_code: catalog_dict}.

    See `polily.tui.i18n.loader` for full semantics.
    """
    return _load_catalogs(directory)
