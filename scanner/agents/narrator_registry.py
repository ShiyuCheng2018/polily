"""Cross-process narrator registry for cancel-running-analysis.

Problem: ScanService is instantiated per-thread (TUI vs dispatcher worker).
Each instance holds its own `_current_narrator`, so the TUI's cancel can't
reach a narrator running under the daemon's ai executor. This module is
the shared lookup table — both sides register by scan_id, either side can
cancel by scan_id.

Thread safety: a lock guards the dict since register/unregister happen
from worker threads and cancel happens from the TUI main loop.
"""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.agents.narrative_writer import NarrativeWriterAgent

_active: dict[str, NarrativeWriterAgent] = {}
_lock = threading.Lock()


def register(scan_id: str, narrator: NarrativeWriterAgent) -> None:
    """Register a narrator under a scan_id so `cancel(scan_id)` can find it."""
    with _lock:
        _active[scan_id] = narrator


def unregister(scan_id: str) -> None:
    """Remove a narrator from the registry. No-op if already gone."""
    with _lock:
        _active.pop(scan_id, None)


def cancel(scan_id: str) -> bool:
    """Cancel the narrator associated with scan_id.

    Returns True if a narrator was found and cancel() was dispatched,
    False if no active narrator matched the scan_id (already finished
    or never registered).
    """
    with _lock:
        narrator = _active.get(scan_id)
    if narrator is None:
        return False
    try:
        narrator.cancel()
        return True
    except Exception:
        return False
