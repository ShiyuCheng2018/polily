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

PLIST_LABEL = "com.polily.scheduler"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def _sweep_legacy_pid_file() -> None:
    """Delete any lingering `data/scheduler.pid` from a pre-v0.9.0 install.

    v0.9.0 moved to launchctl as the authoritative source of truth; the
    PID file is no longer written. Users upgrading from v0.8.5 will have
    one left on disk — remove it on first daemon startup so `ls data/`
    isn't cluttered with orphan state. Safe no-op if file is absent.

    Uses a cwd-relative path because the daemon is launched by launchd
    with `WorkingDirectory` set to the project root (see
    `generate_launchd_plist`). Callers from other contexts must chdir
    first.
    """
    Path("data/scheduler.pid").unlink(missing_ok=True)


def is_daemon_running() -> bool:
    """Check if the scheduler daemon process is actually running.

    launchctl list shows registered services even after the process exits.
    We query the specific label and check for a PID key in the output.
    """
    import subprocess

    result = subprocess.run(
        ["launchctl", "list", PLIST_LABEL],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return False
    # When running: output contains '"PID" = 12345;'
    # When stopped: no PID key in output
    return '"PID"' in result.stdout


def ensure_daemon_running() -> bool:
    """Start the daemon via launchd if not already running, auto-healing
    stale plists (e.g. across package renames).

    Returns True if we started (or regenerated + reloaded) the daemon,
    False if the existing running daemon was kept as-is.
    """
    import subprocess

    working_dir = str(Path.cwd())
    Path(working_dir, "data").mkdir(parents=True, exist_ok=True)
    desired_plist = generate_launchd_plist(working_dir=working_dir)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)

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
    current_plist = PLIST_PATH.read_bytes() if PLIST_PATH.exists() else b""
    if current_plist != desired_plist:
        PLIST_PATH.write_bytes(desired_plist)
        if _only_claude_cli_diff(current_plist, desired_plist):
            logger.info(
                "Plist drift limited to POLILY_CLAUDE_CLI — skipping "
                "unload+load to avoid interrupting in-flight narrator jobs. "
                "New path takes effect on next `polily scheduler restart`."
            )
            return False
        subprocess.run(
            ["launchctl", "unload", str(PLIST_PATH)],
            capture_output=True,
        )
        subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
        logger.info(
            "Regenerated stale plist (content mismatch) and reloaded daemon",
        )
        return True

    if is_daemon_running():
        return False

    # Plist matches but daemon not running — just load.
    subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,
    )
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
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

    # Hard unload any registered service state so the next load is fresh.
    subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,
    )

    # Now boot the new process.
    working_dir = str(Path.cwd())
    Path(working_dir, "data").mkdir(parents=True, exist_ok=True)
    plist_bytes = generate_launchd_plist(working_dir=working_dir)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plist_bytes)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
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
    """
    import plistlib

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

    plist = {
        "Label": PLIST_LABEL,
        "ProgramArguments": [python_path, "-m", "polily.cli", "scheduler", "run"],
        "WorkingDirectory": working_dir,
        "KeepAlive": {"SuccessfulExit": False},
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
    active = db.conn.execute(
        "SELECT COUNT(*) FROM markets WHERE active = 1 AND closed = 0",
    ).fetchone()[0]

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

    def handle_shutdown(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        with contextlib.suppress(Exception):
            scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    try:
        while True:
            signal.pause()
    except AttributeError:
        import time
        while True:
            time.sleep(60)
