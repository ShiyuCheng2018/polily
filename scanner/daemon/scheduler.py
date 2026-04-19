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
import signal
import sys
from pathlib import Path

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from scanner.daemon.poll_job import global_poll, init_poller

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
    """Start the daemon via launchd if not already running.

    Returns True if daemon was started, False if already running.
    Handles the case where the service is registered but process has exited.
    """
    import subprocess

    if is_daemon_running():
        return False

    working_dir = str(Path.cwd())
    Path(working_dir, "data").mkdir(parents=True, exist_ok=True)
    plist_bytes = generate_launchd_plist(working_dir=working_dir)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plist_bytes)

    # Unload first if registered but not running (stale registration)
    subprocess.run(
        ["launchctl", "unload", str(PLIST_PATH)],
        capture_output=True,  # ignore errors if not loaded
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
    import os
    import signal as _signal
    import subprocess
    import time

    pid_path = Path("data/scheduler.pid")
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            try:
                os.kill(pid, 0)  # check alive
                os.kill(pid, _signal.SIGTERM)
                # Brief wait for graceful shutdown (APScheduler flushes pending
                # writes on SIGTERM). If it doesn't exit, launchctl unload below
                # will force the issue.
                time.sleep(1.0)
            except (ProcessLookupError, PermissionError):
                pass  # stale PID, continue to launchctl unload
        except (ValueError, OSError):
            pass  # malformed PID file; ignore

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


def generate_launchd_plist(working_dir: str, python_path: str | None = None) -> bytes:
    """Generate a macOS launchd plist for the scheduler daemon."""
    import plistlib

    if python_path is None:
        python_path = sys.executable

    plist = {
        "Label": PLIST_LABEL,
        "ProgramArguments": [python_path, "-m", "scanner.cli", "scheduler", "run"],
        "WorkingDirectory": working_dir,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


# ---------------------------------------------------------------------------
# Daemon entry point
# ---------------------------------------------------------------------------


def run_daemon(db, config=None) -> None:
    """Daemon entry point: start scheduler, block until SIGTERM.

    v0.7.0: no job restoration — the poll tick drains pending scan_logs rows
    via `dispatch_pending_analyses`, so there's nothing to rehydrate on start.
    """
    from scanner.core.positions import PositionManager
    from scanner.core.wallet import WalletService
    from scanner.daemon.resolution import ResolutionHandler

    # Wire wallet-system services into the poller so auto-resolution runs
    # alongside price polling. Required for v0.6.0+.
    wallet = WalletService(db)
    positions = PositionManager(db)
    resolver = ResolutionHandler(db, wallet, positions)

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
    from scanner.scan_log import fail_orphan_running
    orphans = fail_orphan_running(db)
    if orphans:
        logger.info("Marked %d orphan 'running' rows as failed on startup", orphans)

    # Log startup info to poll.log
    from scanner.daemon.poll_job import _get_poll_log
    plog = _get_poll_log()
    plog.info(f"── daemon started ── {active} markets, poll every 30s ──")
    pending_count = db.conn.execute(
        "SELECT COUNT(*) FROM scan_logs WHERE status='pending'"
    ).fetchone()[0]
    plog.info(f"  pending scan_logs rows: {pending_count}")

    print(f"Polily daemon started — {active} markets, poll every 30s. Ctrl+C to stop.")
    logger.info("Daemon started; %d pending analyses queued", pending_count)

    # Write PID file so `restart_daemon` / CLI `stop` can send SIGTERM.
    import os

    pid_path = Path("data/scheduler.pid")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    def handle_shutdown(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        pid_path.unlink(missing_ok=True)
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
