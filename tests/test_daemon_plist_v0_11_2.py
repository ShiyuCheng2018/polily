"""Verify launchd plist generates the right KeepAlive policy + stderr redirect.

v0.11.2 changes two plist keys:

1. KeepAlive policy migrated from `{"SuccessfulExit": False}` (no restart on
   clean SIGTERM exit-0) to `{"Crashed": True}` (restart on crashes only).

   Why the change: prod daemon was observed dying via SIGTERM exit-0 twice
   in one day (2026-05-04), and KeepAlive's SuccessfulExit:False semantic
   correctly chose NOT to restart -- which left the user without a daemon
   until they noticed and manually restarted. Crashed:True restarts on
   SIGKILL/segfault but respects clean stops via `launchctl unload` (which
   is what `polily scheduler stop` does -- it removes the agent entirely,
   no respawn loop).

2. StandardErrorPath migrated from `/dev/null` to a log file under
   paths.log_dir(). Pre-v0.11.2 swallowed all daemon stderr (including
   logger.exception traces) -- v0.11.2 redirects to a file so future
   bugs are diagnosable. (Test added in Task 4.)
"""
from __future__ import annotations

import plistlib

from polily.daemon.scheduler import generate_launchd_plist


def test_plist_keepalive_policy_is_crashed_true():
    """KeepAlive must be {Crashed: True} so daemon auto-restarts on
    crashes (SIGKILL, segfault, OOM) but respects clean stops via
    launchctl unload."""
    plist_bytes = generate_launchd_plist(working_dir="/tmp/test-working-dir")
    plist = plistlib.loads(plist_bytes)

    assert "KeepAlive" in plist, "plist missing KeepAlive — daemon won't auto-restart"

    keep_alive = plist["KeepAlive"]
    assert isinstance(keep_alive, dict), (
        f"KeepAlive must be a dict (Crashed: True policy), got {type(keep_alive).__name__}"
    )
    assert keep_alive.get("Crashed") is True, (
        f"KeepAlive.Crashed must be True. Got: {keep_alive}. "
        f"Pre-v0.11.2 used {{SuccessfulExit: False}} which doesn't restart "
        f"on clean SIGTERM — caused 2 prod outages 2026-05-04."
    )
    # Should NOT have SuccessfulExit (they're mutually-exclusive design choices)
    assert "SuccessfulExit" not in keep_alive, (
        f"Don't combine SuccessfulExit with Crashed — they conflict. "
        f"Got: {keep_alive}"
    )
