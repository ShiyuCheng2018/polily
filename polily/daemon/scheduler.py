"""APScheduler-based daemon scheduler — dual executor architecture.

Executors:
  - poll (1 thread)  — dedicated to the single global poll job (30s interval)
  - ai   (5 threads) — concurrent AI analyses dispatched from pending scan_logs rows

v0.7.0: scheduled check jobs (date-trigger APScheduler path) were removed.
Dispatching is now DB-driven — the poll tick drains pending rows via
`dispatch_pending_analyses` onto the ai executor.
"""

import contextlib
import logging
import shutil
import signal
import sys
from pathlib import Path

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from polily.daemon.poll_job import global_poll, init_poller

logger = logging.getLogger(__name__)


class WatchScheduler:
    """Dual-executor scheduler: poll (1 thread) + ai (5 threads)."""

    def __init__(self, db, config=None):
        self.db = db
        self.config = config
        executors = {
            "poll": ThreadPoolExecutor(1),
            "ai": ThreadPoolExecutor(5),
        }
        self.scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults={"max_instances": 1, "coalesce": True},
        )

    def start(self):
        """Start the scheduler and register the global poll job."""
        # Suppress noisy APScheduler "max instances reached" warnings
        logging.getLogger("apscheduler.executors").setLevel(logging.ERROR)
        self.scheduler.start()
        # Register the single global poll job on the poll executor
        self.scheduler.add_job(
            global_poll,
            "interval",
            seconds=30,
            id="global_poll",
            executor="poll",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    def shutdown(self):
        self.scheduler.shutdown(wait=True)


# ---------------------------------------------------------------------------
# Launchd integration
# ---------------------------------------------------------------------------

def _plist_label() -> str:
    """Resolve plist Label via paths.launchd_label() (env-overridable).

    Live helper — read on every call so a mid-session
    POLILY_LAUNCHD_LABEL env flip reflects in subsequent plist
    generation / launchctl queries. Production daemons use the default
    "com.polily.scheduler"; dev installs flip the env to
    "com.polily.scheduler.dev" to coexist alongside prod.
    """
    from polily.core import paths
    return paths.launchd_label()


def _plist_path() -> Path:
    """Resolve plist file path via paths.launchd_plist_path().

    Live helper — derived from `_plist_label()` at call time, so the env
    override flows through to file IO sites (`PLIST_PATH.read_bytes`,
    `subprocess.run([..., str(PLIST_PATH)])`, etc.).
    """
    from polily.core import paths
    return paths.launchd_plist_path()


def _resolve_plist_working_dir() -> str:
    """v0.11.0 Whis B1 — anchor the plist's WorkingDirectory to
    paths.data_dir(), NOT Path.cwd().

    Pre-fix the 3 callers (`_migrate_legacy_plist`, `ensure_daemon_running`,
    `restart_daemon`) computed `working_dir = str(Path.cwd())` then
    explicitly `Path(working_dir, 'data').mkdir(...)`. That anchored the
    daemon's WorkingDirectory to whatever cwd the user was in when they
    invoked polily — fragile across shells / `cd /tmp && polily`.

    `paths.data_dir()` lazy-mkdirs internally so callers don't need to
    pre-create. Single source of truth for daemon path resolution.
    """
    from polily.core import paths
    return str(paths.data_dir())


# Snapshot constants kept for backward import compat (some callers /
# tests historically import these directly). The runtime code paths in
# this module use the live helpers `_plist_label()` / `_plist_path()`
# above so a POLILY_LAUNCHD_LABEL env flip mid-session reflects.
PLIST_LABEL = _plist_label()
PLIST_PATH = _plist_path()


def _sweep_legacy_pid_file() -> None:
    """Delete any lingering `scheduler.pid` from a pre-v0.9.0 install.

    v0.9.0 moved to launchctl as the authoritative source of truth; the
    PID file is no longer written. Users upgrading from v0.8.5 will have
    one left on disk — remove it on first daemon startup so the data
    directory isn't cluttered with orphan state. Safe no-op if file is
    absent.

    v0.11.0: target `<paths.data_dir>/scheduler.pid` (the actual location
    on pre-v0.9.0 installs that ran with that dir as cwd) instead of
    cwd-relative `data/scheduler.pid`.
    """
    from polily.core import paths
    (paths.data_dir() / "scheduler.pid").unlink(missing_ok=True)


def is_daemon_running() -> bool:
    """Check if the scheduler daemon process is actually running.

    launchctl list shows registered services even after the process exits.
    We query the specific label and check for a PID key in the output.
    """
    import subprocess

    result = subprocess.run(
        ["launchctl", "list", _plist_label()],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    # When running: output contains '"PID" = 12345;'
    # When stopped: no PID key in output
    return '"PID"' in result.stdout


def _migrate_legacy_plist() -> bool:
    """Whis B2 — one-shot v0.9.x → v0.10.0 plist migration.

    Detects ``--config`` in the on-disk plist's ProgramArguments and
    rewrites without it, then reloads launchctl so the new args take
    effect on the next daemon spawn.

    Returns True if a migration was performed, False otherwise (no plist
    on disk / already modern / non-Darwin / launchctl missing).
    Idempotent — safe to call on every startup; modern plists are read
    once and left untouched.

    Why this exists: pre-v0.10.0 plists embedded ``--config <path>`` in
    ProgramArguments. After T2.5 deleted that flag from the ``scheduler
    run`` subcommand, launchd respawns the daemon → typer rejects the
    unknown arg → non-zero exit → KeepAlive=true → infinite crash loop.
    This helper silently heals the plist on the next TUI launch.

    Note: only writes the new plist + issues unload/load. The full
    auto-heal flow in ``ensure_daemon_running`` re-runs immediately
    after, but it'll see the freshly-written modern plist as matching
    the desired bytes and short-circuit (no double reload).

    SF7 (v0.10.0): platform-guarded so non-Darwin dev boxes / Linux CI
    don't crash on ``FileNotFoundError`` when ``launchctl`` isn't on
    PATH. Also skips when launchctl can't be resolved on Darwin (rare,
    but possible in stripped sandbox environments).
    """
    import subprocess

    # Platform guard — launchctl is macOS-only. On Linux/Windows, the
    # whole concept of a launchd plist doesn't apply.
    if sys.platform != "darwin":
        return False

    # Defense-in-depth: even on Darwin, skip if launchctl can't be found.
    # subprocess.run with FileNotFoundError would propagate out of the
    # daemon-startup auto-heal path and crash the TUI on launch.
    if shutil.which("launchctl") is None:
        return False

    plist_path = _plist_path()
    if not plist_path.exists():
        return False

    content = plist_path.read_text(encoding="utf-8")
    if "--config" not in content:
        return False  # already modern — idempotent no-op

    # Regenerate via the canonical generator — it produces the v0.10.0
    # ProgramArguments shape (no --config, no other dropped flags).
    working_dir = _resolve_plist_working_dir()
    plist_bytes = generate_launchd_plist(working_dir=working_dir)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plist_bytes)

    # Reload so launchd picks up the new args. unload is best-effort —
    # service may not be currently loaded (e.g. first boot, or user ran
    # `launchctl unload` manually). Non-zero rc here is expected and not
    # fatal, but log it for diagnostics.
    unload_result = subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if unload_result.returncode != 0:
        logger.warning(
            "launchctl unload during plist migration returned %d: %s",
            unload_result.returncode,
            unload_result.stderr.strip() or "(no stderr)",
        )

    # load is critical — if it fails, launchd keeps the legacy spec
    # in memory until reboot, defeating B2's whole purpose (the daemon
    # crash-loops because the in-memory plist still carries --config).
    # Propagate so ensure_daemon_running's caller can react.
    try:
        subprocess.run(
            ["launchctl", "load", str(plist_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        logger.error(
            "launchctl load during plist migration failed (rc=%d): %s",
            e.returncode,
            (e.stderr or "").strip() or "(no stderr)",
        )
        raise
    return True


def ensure_daemon_running() -> bool:
    """Start the daemon via launchd if not already running, auto-healing
    stale plists (e.g. across package renames).

    Returns True if we started (or regenerated + reloaded) the daemon,
    False if the existing running daemon was kept as-is.
    """
    import subprocess

    # B2: one-shot heal of legacy plists carrying `--config` from v0.9.x.
    # If the migration runs, it already wrote new bytes + reloaded — fall
    # through anyway so the rest of the auto-heal logic stays the source
    # of truth for "is daemon running" reporting.
    _migrate_legacy_plist()

    plist_path = _plist_path()
    working_dir = _resolve_plist_working_dir()
    desired_plist = generate_launchd_plist(working_dir=working_dir)
    plist_path.parent.mkdir(parents=True, exist_ok=True)

    # Content-match check — if the on-disk plist points at a module that
    # no longer exists (classic symptom after a package rename upgrade),
    # the running daemon will crash-loop silently. Rewrite + reload
    # regardless of what launchctl currently reports.
    #
    # v0.9.1 refinement: if the ONLY difference is POLILY_CLAUDE_CLI
    # (user switched nvm / homebrew versions since the plist was
    # generated), skip the unload+load — running daemon stays alive,
    # in-flight narrator jobs don't get SIGTERMed. Write the new bytes
    # so the next deliberate restart picks up the new path; BaseAgent's
    # dangling-path self-check handles the "current daemon's env var
    # is stale" case at job-invocation time.
    current_plist = plist_path.read_bytes() if plist_path.exists() else b""
    if current_plist != desired_plist:
        plist_path.write_bytes(desired_plist)
        if _only_claude_cli_diff(current_plist, desired_plist):
            logger.info(
                "Plist drift limited to POLILY_CLAUDE_CLI — skipping "
                "unload+load to avoid interrupting in-flight narrator jobs. "
                "New path takes effect on next `polily scheduler restart`."
            )
            return False
        subprocess.run(
            ["launchctl", "unload", str(plist_path)],
            capture_output=True,
        )
        subprocess.run(["launchctl", "load", str(plist_path)], check=True)
        logger.info(
            "Regenerated stale plist (content mismatch) and reloaded daemon",
        )
        return True

    if is_daemon_running():
        return False

    # Plist matches but daemon not running — just load.
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    logger.info("Auto-started scheduler daemon via launchd")
    return True


def restart_daemon() -> bool:
    """Stop the running daemon (if any) + start fresh via launchd.

    Always boots a new Python process, so code changes since the last
    daemon start take effect. TUI calls this on mount so the user picks
    up the latest code just by reopening the app.

    Returns True if a daemon is running after the call (success).
    """
    import subprocess
    import time

    from polily.daemon.launchctl_query import is_daemon_running, kill_daemon

    # Graceful shutdown via launchctl kill TERM — APScheduler handler flushes
    # pending writes before exit. If the kill fails (not registered, launchctl
    # missing, daemon already dead), we still fall through to `launchctl
    # unload` below as the hard cleanup — preserves the old "stale PID,
    # continue to launchctl unload" intent.
    if is_daemon_running():
        kill_daemon("TERM")
        time.sleep(1.0)

    plist_path = _plist_path()

    # Hard unload any registered service state so the next load is fresh.
    subprocess.run(
        ["launchctl", "unload", str(plist_path)],
        capture_output=True,
    )

    # Now boot the new process.
    working_dir = _resolve_plist_working_dir()
    plist_bytes = generate_launchd_plist(working_dir=working_dir)
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_bytes(plist_bytes)
    subprocess.run(["launchctl", "load", str(plist_path)], check=True)
    logger.info("Restarted scheduler daemon via launchd")
    return True


def generate_launchd_plist(
    working_dir: str,
    python_path: str | None = None,
    claude_cli: str | None = None,
) -> bytes:
    """Generate a macOS launchd plist for the scheduler daemon.

    claude_cli: absolute path to the `claude` CLI. If omitted, resolved
        via `shutil.which("claude")` in the caller's PATH (which is the
        user's shell PATH when this runs from `polily` CLI or TUI). The
        resolved path is written into EnvironmentVariables.POLILY_CLAUDE_CLI
        so the launchd-spawned daemon — whose PATH is the stripped
        `/usr/local/bin:/usr/bin:/bin` — can still invoke the binary.

        Why not extend PATH instead? launchd does no `$VAR` / glob
        expansion on EnvironmentVariables, and extending PATH silently
        resolves to the wrong version when the user has both an nvm-
        installed and a Homebrew-installed claude (POC confirmed). An
        absolute path is the only deterministic contract.

        If `shutil.which` returns None (claude not installed yet — first
        onboard), the key is omitted from the plist. BaseAgent falls
        back to bare `"claude"` and fails with a clean stderr on the
        first narrator job, which surfaces in scan_logs instead of
        crashing the daemon.

    v0.11.0 additions:
    - EnvironmentVariables propagates POLILY_DATA_DIR (always — daemon
      and TUI MUST agree on db location since they share the SQLite
      file) and POLILY_LOG_DIR (only if explicitly set; default
      data_dir/logs is computed identically by either side, no need
      to enshrine).
    - Label resolves via paths.launchd_label() so a dev daemon can run
      under com.polily.scheduler.dev alongside prod com.polily.scheduler.
    """
    import os as _os
    import plistlib

    from polily.core import paths as _paths

    if python_path is None:
        python_path = sys.executable
    if claude_cli is None:
        claude_cli = shutil.which("claude")

    env: dict[str, str] = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
    }
    if claude_cli:
        env["POLILY_CLAUDE_CLI"] = claude_cli
    else:
        logger.warning(
            "claude CLI not found on PATH when generating launchd plist. "
            "Daemon's NarrativeWriter jobs will fail until you install "
            "claude and run `polily scheduler restart`."
        )

    # v0.11.0: propagate POLILY_DATA_DIR. Always set, since the daemon
    # MUST agree with the parent on path resolution (they share the
    # SQLite database file).
    env["POLILY_DATA_DIR"] = str(_paths.data_dir())

    # v0.11.0: propagate POLILY_LOG_DIR only if explicitly set. Default
    # (data_dir/logs) is computed by the daemon's own paths module, no
    # need to enshrine it in the plist.
    if "POLILY_LOG_DIR" in _os.environ:
        env["POLILY_LOG_DIR"] = _os.environ["POLILY_LOG_DIR"]

    plist = {
        "Label": _plist_label(),
        "ProgramArguments": [python_path, "-m", "polily.cli", "scheduler", "run"],
        "WorkingDirectory": working_dir,
        # v0.11.2: switched from {"SuccessfulExit": False} to {"Crashed": True}.
        #
        # Per Apple's launchd.plist(5): `Crashed` = True restarts on abnormal
        # exits — SIGKILL, SIGSEGV/SIGBUS, SIGABRT, OOM-kill, AND any non-zero
        # exit code (including os._exit(1) from a polily code error). It does
        # NOT trigger on:
        #   - clean exit(0) (e.g., SIGTERM handler that exits cleanly)
        #   - launchctl bootout / unload (which removes the agent entirely
        #     BEFORE any signal lands, so neither KeepAlive policy ever sees
        #     this path)
        #
        # `polily scheduler stop` → calls `launchctl unload` (verified in this
        # file's stop_daemon function) → daemon agent is removed before SIGTERM
        # is sent → no false-positive restart on user-initiated stops.
        #
        # Pre-v0.11.2 prod daemon died via clean SIGTERM exit-0 twice on
        # 2026-05-04 and `SuccessfulExit: False` correctly DIDN'T restart,
        # leaving the user without a polling daemon. `Crashed: True` is more
        # protective: covers crashes (signals + non-zero exits) without
        # restarting on legitimate clean stops.
        "KeepAlive": {"Crashed": True},
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "EnvironmentVariables": env,
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


def _only_claude_cli_diff(old_bytes: bytes, new_bytes: bytes) -> bool:
    """True iff the only difference between two plists is
    EnvironmentVariables.POLILY_CLAUDE_CLI. Used to decide whether a
    plist regeneration is worth interrupting the running daemon.

    Handles the "old plist predates POLILY_CLAUDE_CLI entirely" case
    (upgrade from v0.9.0) — that's NOT claude-only diff, so returns
    False and forces a reload (which is what we want; old daemon
    doesn't know about the env var at all).
    """
    import plistlib
    try:
        old = plistlib.loads(old_bytes)
        new = plistlib.loads(new_bytes)
    except Exception:
        return False  # unparsable old → definitely reload

    # plistlib.loads can return non-dict values (None, list, str) when
    # the input parses as valid XML/binary plist but isn't a top-level
    # dict — e.g. a stub `<plist>...</plist>` wrapper returns None. We
    # can't compare env dicts in that case; force reload.
    if not isinstance(old, dict) or not isinstance(new, dict):
        return False

    # If old plist is missing POLILY_CLAUDE_CLI entirely but new has it,
    # there's no other diff — still fine to skip reload (the running
    # daemon's narrator will fall back to bare 'claude', fail with clear
    # error, user runs `polily scheduler restart`). But to be
    # conservative on the migration path, only treat it as "claude-only"
    # when BOTH had the key (i.e. it's a post-install path swap, not
    # first-time plist upgrade).
    old_env = old.get("EnvironmentVariables", {}) or {}
    new_env = new.get("EnvironmentVariables", {}) or {}
    if "POLILY_CLAUDE_CLI" not in old_env:
        return False
    if "POLILY_CLAUDE_CLI" not in new_env:
        return False

    # Normalize: remove POLILY_CLAUDE_CLI from both sides' env dicts.
    def _strip(p: dict) -> dict:
        env = dict(p.get("EnvironmentVariables", {}))
        env.pop("POLILY_CLAUDE_CLI", None)
        out = dict(p)
        out["EnvironmentVariables"] = env
        return out

    return _strip(old) == _strip(new)


# ---------------------------------------------------------------------------
# Daemon entry point
# ---------------------------------------------------------------------------


def _build_shutdown_handler(scheduler):
    """Build the SIGTERM/SIGINT handler for `run_daemon`.

    Factored out for unit-testability — the closure form was inlined inside
    `run_daemon` and couldn't be exercised without bringing up a real daemon.

    Behavior:
    - Writes a `── shutting down (SIGTERM) ──` marker to the poll log so
      post-mortem can distinguish kill-by-signal from "Python crashed
      mid-poll" (the daemon's stderr goes to /dev/null via the launchd
      plist, so logger.info is invisible — the poll log is the only
      visible record).
    - Writes the marker BEFORE `scheduler.shutdown` because APScheduler may
      tear down logger handlers as part of its shutdown sequence.
    - Both writes are wrapped in `contextlib.suppress(Exception)` —
      raising inside a signal handler causes an uglier death than just
      losing the marker. Logging is best-effort.
    """
    def handle_shutdown(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        with contextlib.suppress(Exception):
            from polily.daemon.poll_job import _get_poll_log
            sig_name = {
                signal.SIGTERM: "SIGTERM",
                signal.SIGINT: "SIGINT",
            }.get(signum, f"signal {signum}")
            _get_poll_log().info(f"── shutting down ({sig_name}) ──")
        with contextlib.suppress(Exception):
            scheduler.shutdown(wait=False)
        sys.exit(0)

    return handle_shutdown


def _count_monitored_active_markets(db) -> int:
    """v0.10.1 — count of markets the daemon's poll cycle will actually
    fetch every 30s. Same JOIN+WHERE as `_get_monitored_markets` in
    poll_job.py:889. Used by the daemon startup banner so the printed
    `X markets, poll every 30s` line matches what subsequent poll
    cycles report.

    Pre-fix the banner used `SELECT COUNT(*) FROM markets WHERE
    active=1 AND closed=0` without the event_monitors JOIN, so phantom
    markets from previously-scanned-but-no-longer-monitored events
    inflated the count, drifting from the real `clob N markets` poll
    line over time. Extracted into a helper (rather than inlined SQL)
    so tests can import and exercise the production path directly.
    """
    return db.conn.execute(
        """SELECT COUNT(*) FROM markets m
           JOIN event_monitors em ON m.event_id = em.event_id
           WHERE m.active = 1 AND m.closed = 0 AND em.auto_monitor = 1""",
    ).fetchone()[0]


def run_daemon(db, config=None) -> None:
    """Daemon entry point: start scheduler, block until SIGTERM.

    v0.7.0: no job restoration — the poll tick drains pending scan_logs rows
    via `dispatch_pending_analyses`, so there's nothing to rehydrate on start.
    """
    from polily.core.positions import PositionManager
    from polily.core.wallet import WalletService
    from polily.daemon.resolution import ResolutionHandler

    # Wire wallet-system services into the poller so auto-resolution runs
    # alongside price polling. Required for v0.6.0+.
    wallet = WalletService(db)
    positions = PositionManager(db)
    resolver = ResolutionHandler(db, wallet, positions)

    # v0.8.5: one-time backfill of rows stuck in SETTLING from pre-v0.8.5 gate
    import asyncio as _asyncio

    from polily.daemon.poll_job import backfill_stuck_resolutions
    try:
        n = _asyncio.run(
            backfill_stuck_resolutions(db, wallet, positions, resolver)
        )
        if n > 0:
            from polily.daemon.poll_job import _get_poll_log
            _get_poll_log().info(f"startup-backfill| processed {n} stuck markets")
    except Exception:
        logger.exception("backfill_stuck_resolutions failed; skipping")

    # Create scheduler BEFORE init_poller so the dispatcher step in
    # global_poll (guarded by `if _ctx and _ctx.scheduler`) can actually
    # submit jobs. Without this, v0.7.0's whole dispatcher is a no-op.
    scheduler = WatchScheduler(db, config=config)

    init_poller(
        db=db,
        wallet=wallet,
        positions=positions,
        resolver=resolver,
        config=config,
        scheduler=scheduler.scheduler,
    )

    # Count active markets for startup message
    active = _count_monitored_active_markets(db)

    scheduler.start()

    # v0.7.0: scrub orphan running rows from a prior crash.
    from polily.scan_log import fail_orphan_running
    orphans = fail_orphan_running(db)
    if orphans:
        logger.info("Marked %d orphan 'running' rows as failed on startup", orphans)

    # Log startup info to poll.log
    from polily.daemon.poll_job import _get_poll_log
    plog = _get_poll_log()
    plog.info(f"── daemon started ── {active} markets, poll every 30s ──")
    pending_count = db.conn.execute(
        "SELECT COUNT(*) FROM scan_logs WHERE status='pending'"
    ).fetchone()[0]
    plog.info(f"  pending scan_logs rows: {pending_count}")

    print(f"Polily daemon started — {active} markets, poll every 30s. Ctrl+C to stop.")
    logger.info("Daemon started; %d pending analyses queued", pending_count)

    # v0.9.0: launchctl is the authoritative "is daemon running?" registry;
    # we no longer write data/scheduler.pid. Sweep any lingering file
    # from a pre-v0.9.0 install so it doesn't confuse `ls data/`.
    _sweep_legacy_pid_file()

    handle_shutdown = _build_shutdown_handler(scheduler)
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        while True:
            signal.pause()
    except AttributeError:
        import time
        while True:
            time.sleep(60)
