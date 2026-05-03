"""Path resolution for polily — single source of truth for all on-disk
locations (db, logs, plist).

Three-layer resolution, highest priority first:

1. CLI override — set via ``set_data_dir_override(p)`` from
   ``polily/cli.py``'s top-level callback when the user passes
   ``--data-dir=PATH``. Module-level state (process-scoped).
2. Environment variable — ``POLILY_DATA_DIR`` / ``POLILY_LOG_DIR``.
   Read on every call (cheap; allows ``monkeypatch.setenv`` test
   isolation).
3. Default — ``platformdirs.user_data_dir("polily", appauthor=False)``.
   macOS: ``~/Library/Application Support/polily/``.
   Linux: ``$XDG_DATA_HOME/polily`` or ``~/.local/share/polily/``.

``log_dir()`` defaults to ``data_dir() / "logs"`` (NOT
``platformdirs.user_log_dir``) so a single ``POLILY_DATA_DIR`` env
covers both. ``POLILY_LOG_DIR`` exists as an escape hatch.

``launchd_label()`` reads ``POLILY_LAUNCHD_LABEL`` (default
``com.polily.scheduler``) so a dev daemon can run alongside prod under
``com.polily.scheduler.dev`` without launchctl conflicts.

Directory creation is lazy — first call to ``data_dir()`` /
``log_dir()`` mkdir's the path. Repeated calls are idempotent.
"""
from __future__ import annotations

import os
from pathlib import Path

import platformdirs

_APP_NAME = "polily"

# Module-level CLI overrides. Set once from cli.py's top-level callback
# (or from test fixtures via set_*_override). Process-scoped state.
_DATA_DIR_OVERRIDE: Path | None = None
_LOG_DIR_OVERRIDE: Path | None = None


def set_data_dir_override(p: Path | str | None) -> None:
    """Set the CLI-flag-tier override for data dir. Pass None to clear."""
    global _DATA_DIR_OVERRIDE
    _DATA_DIR_OVERRIDE = Path(p) if p is not None else None


def set_log_dir_override(p: Path | str | None) -> None:
    """Set the CLI-flag-tier override for log dir. Pass None to clear."""
    global _LOG_DIR_OVERRIDE
    _LOG_DIR_OVERRIDE = Path(p) if p is not None else None


def data_dir() -> Path:
    """Resolve the polily data directory.

    Resolution order: CLI override > POLILY_DATA_DIR env >
    platformdirs.user_data_dir('polily'). Created on first access.
    """
    if _DATA_DIR_OVERRIDE is not None:
        result = _DATA_DIR_OVERRIDE
    else:
        env = os.environ.get("POLILY_DATA_DIR")
        if env:
            result = Path(env)
        else:
            result = Path(platformdirs.user_data_dir(_APP_NAME, appauthor=False))
    result.mkdir(parents=True, exist_ok=True)
    return result


def log_dir() -> Path:
    """Resolve the polily log directory.

    Resolution order: CLI override > POLILY_LOG_DIR env >
    ``data_dir() / 'logs'``. Created on first access.
    """
    if _LOG_DIR_OVERRIDE is not None:
        result = _LOG_DIR_OVERRIDE
    else:
        env = os.environ.get("POLILY_LOG_DIR")
        result = Path(env) if env else (data_dir() / "logs")
    result.mkdir(parents=True, exist_ok=True)
    return result


def db_path() -> Path:
    """Path to the SQLite database file. Always ``data_dir() / 'polily.db'``."""
    return data_dir() / "polily.db"


def agent_feedback_log() -> Path:
    """Path to ``agent_feedback.log`` — narrative_writer dev-feedback append log."""
    return log_dir() / "agent_feedback.log"


def agent_debug_log() -> Path:
    """Path to ``agent_debug.log`` — BaseAgent stdout/stderr debug dump."""
    return log_dir() / "agent_debug.log"


def launchd_label() -> str:
    """Launchd plist Label. Defaults to ``com.polily.scheduler``; overridden
    by ``POLILY_LAUNCHD_LABEL`` env var so dev daemons can use
    ``com.polily.scheduler.dev`` and coexist with prod."""
    return os.environ.get("POLILY_LAUNCHD_LABEL", "com.polily.scheduler")


def launchd_plist_path() -> Path:
    """``~/Library/LaunchAgents/<label>.plist`` derived from launchd_label()."""
    return Path.home() / "Library" / "LaunchAgents" / f"{launchd_label()}.plist"


def legacy_data_dir() -> Path:
    """Pre-v0.11.0 data location: ``$CWD/data``. Used ONLY by first-launch
    migration to detect and copy legacy installs. NEVER returned by
    ``data_dir()``."""
    return Path.cwd() / "data"


def legacy_db_path() -> Path:
    """Pre-v0.11.0 db location: ``$CWD/data/polily.db``. Migration-only."""
    return legacy_data_dir() / "polily.db"
