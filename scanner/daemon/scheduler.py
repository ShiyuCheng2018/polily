"""APScheduler-based daemon scheduler — dual executor architecture.

Executors:
  - poll (1 thread)  — dedicated to the single global poll job (10s interval)
  - ai   (5 threads) — concurrent AI analyses (movement-triggered + scheduled check_jobs)

Jobs are restored from event_monitors table on startup. No SQLAlchemy needed.
"""

import logging
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from scanner.core.monitor_store import get_active_monitors, get_event_monitor
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
        self.scheduler.start()
        # Register the single global poll job on the poll executor
        self.scheduler.add_job(
            global_poll,
            "interval",
            seconds=10,
            id="global_poll",
            executor="poll",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    def shutdown(self):
        self.scheduler.shutdown(wait=True)

    def restore_check_jobs(self) -> int:
        """Restore check jobs from event_monitors with next_check_at.

        Returns the number of jobs restored.
        """
        event_ids = get_active_monitors(self.db)
        now = datetime.now(UTC)
        count = 0
        for eid in event_ids:
            mon = get_event_monitor(eid, self.db)
            if not mon or not mon.get("next_check_at"):
                continue
            try:
                check_at = datetime.fromisoformat(mon["next_check_at"])
                # Ensure timezone-aware for comparison
                if check_at.tzinfo is None:
                    check_at = check_at.replace(tzinfo=UTC)
            except ValueError:
                logger.warning("Invalid next_check_at for %s: %s", eid, mon["next_check_at"])
                continue

            if check_at <= now:
                # Overdue — schedule 5 seconds from now
                run_at = now + timedelta(seconds=5)
            else:
                run_at = check_at

            self.schedule_check(eid, run_at)
            count += 1
        logger.info("Restored %d check jobs from DB", count)
        return count

    def schedule_check(self, event_id: str, run_at: datetime) -> None:
        """Schedule a check job for an event at the given time."""
        self.scheduler.add_job(
            _execute_check,
            "date",
            run_date=run_at,
            id=f"check_{event_id}",
            executor="ai",
            replace_existing=True,
            misfire_grace_time=3600,
            kwargs={
                "event_id": event_id,
                "db": self.db,
                "config": self.config,
                "watch_scheduler": self,
            },
        )
        logger.info("Scheduled check for %s at %s", event_id, run_at)

    def cancel_check(self, event_id: str) -> None:
        """Cancel a scheduled check job. No-op if not found."""
        try:
            self.scheduler.remove_job(f"check_{event_id}")
            logger.info("Cancelled check for %s", event_id)
        except Exception:
            pass

    def list_pending(self) -> list[dict]:
        """List all pending scheduled jobs."""
        jobs = self.scheduler.get_jobs()
        return [{"job_id": j.id, "next_run": j.next_run_time} for j in jobs]


def _execute_check(event_id: str, db, config=None, watch_scheduler=None) -> None:
    """Job function called by APScheduler for scheduled event checks.

    Placeholder: will call recheck_event (Task 3.5) once implemented.
    """
    logger.info("Executing scheduled check for event %s", event_id)
    try:
        from scanner.daemon.recheck import recheck_event

        result = recheck_event(event_id, db=db, trigger_source="scheduled")
        logger.info("Check result for %s: %s", event_id, result)

        # Re-schedule if result provides a next_check_at
        if watch_scheduler is not None and hasattr(result, "next_check_at") and result.next_check_at:
            try:
                next_time = datetime.fromisoformat(result.next_check_at)
                watch_scheduler.schedule_check(event_id, next_time)
                logger.info("Re-scheduled %s for %s", event_id, result.next_check_at)
            except ValueError:
                logger.warning("Invalid next_check_at for %s: %s", event_id, result.next_check_at)
    except ImportError:
        logger.warning("recheck_event not yet implemented (Task 3.5), skipping check for %s", event_id)
    except Exception:
        logger.exception("Check failed for event %s", event_id)


# ---------------------------------------------------------------------------
# Launchd integration
# ---------------------------------------------------------------------------

PLIST_LABEL = "com.polily.scheduler"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{PLIST_LABEL}.plist"


def is_daemon_running() -> bool:
    """Check if the scheduler daemon is running via launchd."""
    import subprocess

    result = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    return PLIST_LABEL in result.stdout


def ensure_daemon_running() -> bool:
    """Start the daemon via launchd if not already running.

    Returns True if daemon was started, False if already running.
    """
    import subprocess

    if is_daemon_running():
        return False

    working_dir = str(Path.cwd())
    Path(working_dir, "data").mkdir(parents=True, exist_ok=True)
    plist_bytes = generate_launchd_plist(working_dir=working_dir)
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_bytes(plist_bytes)
    subprocess.run(["launchctl", "load", str(PLIST_PATH)], check=True)
    logger.info("Auto-started scheduler daemon via launchd")
    return True


def generate_launchd_plist(working_dir: str, python_path: str | None = None) -> bytes:
    """Generate a macOS launchd plist for the scheduler daemon."""
    import plistlib

    if python_path is None:
        python_path = sys.executable

    log_path = f"{working_dir}/data/scheduler.log"
    plist = {
        "Label": PLIST_LABEL,
        "ProgramArguments": [python_path, "-m", "scanner.cli", "scheduler", "run"],
        "WorkingDirectory": working_dir,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": log_path,
        "StandardErrorPath": log_path,
        "EnvironmentVariables": {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    }
    return plistlib.dumps(plist, fmt=plistlib.FMT_XML)


# ---------------------------------------------------------------------------
# Daemon entry point
# ---------------------------------------------------------------------------


def run_daemon(db, config=None) -> None:
    """Daemon entry point: start scheduler, restore jobs, block until SIGTERM."""
    # Initialize poller context before starting scheduler
    init_poller(db=db, config=config)

    scheduler = WatchScheduler(db, config=config)
    scheduler.start()
    restored = scheduler.restore_check_jobs()

    logger.info("Daemon started with %d check jobs", restored)

    # Write PID file for SIGUSR1 notification
    import os

    pid_path = Path("data/scheduler.pid")
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()))

    def handle_shutdown(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        pid_path.unlink(missing_ok=True)
        scheduler.shutdown()
        sys.exit(0)

    _reload_requested = False

    def handle_reload(signum, frame):
        nonlocal _reload_requested
        _reload_requested = True

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    signal.signal(signal.SIGUSR1, handle_reload)

    # Block until signal; reload jobs when SIGUSR1 flag is set
    try:
        while True:
            signal.pause()
            if _reload_requested:
                _reload_requested = False
                logger.info("Reloading check jobs from DB (SIGUSR1)")
                scheduler.restore_check_jobs()
    except AttributeError:
        # Windows doesn't have signal.pause
        import time

        while True:
            time.sleep(60)
