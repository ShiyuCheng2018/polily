"""launchctl-backed daemon aliveness queries + signal delivery.

Replaces the legacy `data/scheduler.pid` file as the source of truth for
"is the scheduler daemon running, and if so what's its PID?". launchctl
is the authoritative registry — the .pid approach could get out of sync
with reality when the daemon was SIGKILL'd, when launchctl auto-
restarted under KeepAlive=true, or during the 1-2s restart window where
the old daemon had unlinked its PID and the new one hadn't written its
own yet. Using launchctl directly removes the whole class of bug.

Performance: `launchctl list com.polily.scheduler` takes ~5ms per call
on an M-series Mac; the TUI sidebar's 12 calls/minute cost ~65ms CPU
per minute. Negligible for the correctness win.

macOS-only module — launchctl doesn't exist on Linux/Windows. Polily
is already macOS-only (launchd daemon + Nerd Font terminal), so this
inherits the platform gate.
"""
from __future__ import annotations

import os
import re
import subprocess

LABEL = "com.polily.scheduler"

# launchctl list prints values like `"PID" = 43384;`. The regex tolerates
# arbitrary whitespace around the `=`.
_PID_RE = re.compile(r'"PID"\s*=\s*(\d+)\s*;')


def _service_target() -> str:
    """`gui/<uid>/<label>` — the launchctl service-target string for
    this user's LaunchAgent (installed under ~/Library/LaunchAgents/)."""
    return f"gui/{os.geteuid()}/{LABEL}"


def get_daemon_pid() -> int | None:
    """Return the live daemon PID, or None if not running.

    Handles 3 launchctl states:
    - Running: stdout contains `"PID" = N;`
    - Registered but not running (e.g. last crashed, pending restart): stdout
      is a dict without a `"PID"` line
    - Not registered: returncode != 0 with error on stderr

    Also tolerates subprocess failures (timeout, launchctl missing) by
    returning None — a failed query should never crash the caller.
    """
    try:
        result = subprocess.run(
            ["launchctl", "list", LABEL],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    if result.returncode != 0:
        return None

    match = _PID_RE.search(result.stdout)
    return int(match.group(1)) if match else None


def is_daemon_running() -> bool:
    """Convenience boolean wrapper over `get_daemon_pid`."""
    return get_daemon_pid() is not None


def kill_daemon(sig: str = "TERM") -> bool:
    """Send a signal to the daemon via `launchctl kill <sig> gui/<uid>/<label>`.

    Returns True if the subprocess call itself succeeded (returncode 0),
    False otherwise (not registered, launchctl missing, timeout, etc.) —
    mirrors the old `os.kill(pid, SIG) + ProcessLookupError` swallow
    semantics. Callers typically follow with `time.sleep(1.0)` for grace
    and then `launchctl unload` as the hard cleanup, so a kill failure
    here is usually not fatal.

    `sig` is a launchctl signal name: TERM, KILL, USR1, HUP, etc.
    """
    try:
        result = subprocess.run(
            ["launchctl", "kill", sig, _service_target()],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return False
    return result.returncode == 0
