"""In-process narrator registry for cancel-running-analysis.

Scope: **process-local**. The module-level ``_active`` dict lives in one
Python interpreter. It lets threads within the same process share the
`{scan_id: NarrativeWriterAgent}` lookup — e.g. the TUI main loop
can find a narrator that the ai-executor thread registered.

It does **NOT** cross process boundaries. The Polily daemon runs as a
separate OS process (launched via launchd/subprocess), so analyses
dispatched by the daemon register with the daemon's registry, not the
TUI's. When a user hits `c` in the TUI for a dispatcher-initiated row:

- The TUI's `cancel_running_scan` flips the DB row to 'cancelled'.
- `cancel(scan_id)` in the TUI's registry returns False (miss — the
  narrator belongs to the daemon process).
- The daemon's narrator continues running until it finishes.
- When it finishes, `finish_scan(status='completed')` is a no-op
  because the row is no longer 'running' (see scan_log.py).
- `analyze_event` detects rowcount=0 and skips the supersede+insert
  step, so no phantom pending row is produced.

Upshot: the user's DB-level cancel intent is honored, but the narrator
subprocess still burns through its Claude quota. A proper cross-process
cancel would need DB-backed signaling (e.g. a `scan_logs.cancel_requested`
column the daemon polls each tick) — deferred to a later release.

Thread safety: a lock guards the dict since register/unregister happen
from worker threads and cancel happens from the main loop.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.agents.narrative_writer import NarrativeWriterAgent

logger = logging.getLogger(__name__)

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
        logger.exception("narrator.cancel() raised for scan_id=%s", scan_id)
        return False
