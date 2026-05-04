"""Verify launchd plist generates the right KeepAlive policy + stderr redirect.

v0.11.2 introduced two plist changes:

1. **KeepAlive policy** -- v0.11.2 set this to `{"Crashed": True}` thinking
   it would mean "restart on crash but respect clean stops". This was wrong:
   per Apple's launchd semantics, dict-style KeepAlive with `Crashed: True`
   means "the daemon should be running ONLY IF the previous exit was a
   crash". On `launchctl load`, there is no previous exit, so the condition
   is false -> daemon never starts. Symptom: TUI launch -> plist regenerated
   correctly -> launchctl load returns 0 -> but daemon stays at PID `-`
   forever until forcibly kickstarted.

   v0.11.3 reverts to **`KeepAlive: True`** (boolean) -- launchd's "always
   keep alive" mode. Daemon starts on load, restarts on any exit. The
   original v0.11.1 concern about "infinite crash loop" is mitigated by
   launchd's built-in 10s restart throttle. User-initiated stop goes
   through `launchctl unload` (which `polily scheduler stop` already does)
   -- unload removes the agent entirely, no respawn loop.

2. StandardErrorPath migrated from `/dev/null` to a log file under
   paths.log_dir(). Pre-v0.11.2 swallowed all daemon stderr (including
   logger.exception traces) -- v0.11.2 redirects to a file so future
   bugs are diagnosable. Unchanged in v0.11.3.
"""
from __future__ import annotations

import plistlib

from polily.daemon.scheduler import generate_launchd_plist


def test_plist_keepalive_is_unconditional_true():
    """KeepAlive must be the boolean True so launchd starts the daemon on
    load and restarts on any exit.

    v0.11.2 used `{"Crashed": True}` which broke initial launch (Apple
    semantic: 'restart only if previous exit was crash' -> on first load
    with no previous exit, condition is false -> daemon never starts).
    User-initiated stop is handled by `polily scheduler stop` calling
    `launchctl unload` (removes the agent entirely; no respawn).
    """
    plist_bytes = generate_launchd_plist(working_dir="/tmp/test-working-dir")
    plist = plistlib.loads(plist_bytes)

    assert "KeepAlive" in plist, "plist missing KeepAlive — daemon won't auto-restart"

    keep_alive = plist["KeepAlive"]
    assert keep_alive is True, (
        f"KeepAlive must be the boolean `True`, got {keep_alive!r} "
        f"({type(keep_alive).__name__}). v0.11.2's `{{Crashed: True}}` "
        f"caused initial-launch failure: launchd reads it as 'only run if "
        f"previous exit was a crash', and on first load there is no previous "
        f"exit, so the daemon never starts."
    )


def test_plist_stderr_path_redirects_to_log_file():
    """StandardErrorPath must point at a real log file so logger.exception
    traces are captured.

    Pre-v0.11.2: StandardErrorPath = /dev/null swallowed all daemon stderr,
    making BUG-2 (dispatcher exception) impossible to diagnose. Even with
    BUG-2 not yet fixed, this stderr redirect is independently valuable
    for any other future bug investigation.
    """
    plist_bytes = generate_launchd_plist(working_dir="/tmp/test-working-dir")
    plist = plistlib.loads(plist_bytes)

    stderr = plist.get("StandardErrorPath", "")
    assert stderr != "/dev/null", (
        "StandardErrorPath = /dev/null swallows daemon stderr — "
        "makes future bug diagnostics impossible. Should point at a "
        "path under polily.core.paths.log_dir()."
    )
    assert "logs" in stderr or "polily" in stderr.lower(), (
        f"StandardErrorPath should be under polily's log_dir. Got: {stderr}"
    )
