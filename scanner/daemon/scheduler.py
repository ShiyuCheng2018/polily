"""APScheduler-based watch scheduler with MemoryJobStore.

Jobs are restored from market_states table on startup. No SQLAlchemy needed.
"""

import logging
import signal
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from scanner.core.monitor_store import get_active_monitors

logger = logging.getLogger(__name__)


class WatchScheduler:
    """Schedule watch rechecks at exact next_check_at times."""

    def __init__(self, db, config=None):
        self.db = db
        self.config = config
        executors = {"default": ThreadPoolExecutor(1)}
        self.scheduler = BackgroundScheduler(
            executors=executors,
            job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 3600},
        )

    def start(self):
        self.scheduler.start()

    def shutdown(self):
        self.scheduler.shutdown(wait=True)

    def schedule(self, market_id: str, run_at: datetime) -> None:
        """Schedule a recheck at an exact time. Replaces existing job for same market."""
        self.scheduler.add_job(
            _execute_recheck,
            trigger="date",
            run_date=run_at,
            id=market_id,
            replace_existing=True,
            kwargs={"market_id": market_id, "db": self.db, "config": self.config, "watch_scheduler": self},
        )
        logger.info("Scheduled recheck for %s at %s", market_id, run_at)

    def cancel(self, market_id: str) -> None:
        """Cancel a scheduled recheck. No-op if not found."""
        try:
            self.scheduler.remove_job(market_id)
            logger.info("Cancelled recheck for %s", market_id)
        except Exception:
            pass

    def list_pending(self) -> list[dict]:
        """List all pending scheduled jobs."""
        jobs = self.scheduler.get_jobs()
        return [{"market_id": j.id, "next_run": j.next_run_time} for j in jobs]

    def restore_from_db(self) -> int:
        """On startup, restore jobs from event_monitors table.

        Returns the number of jobs restored.
        """
        event_ids = get_active_monitors(self.db)
        now = datetime.now(UTC)
        count = 0
        for eid in event_ids:
            from scanner.core.monitor_store import get_event_monitor
            mon = get_event_monitor(eid, self.db)
            if not mon or not mon.get("next_check_at"):
                continue
            try:
                check_at = datetime.fromisoformat(mon["next_check_at"])
            except ValueError:
                logger.warning("Invalid next_check_at for %s: %s", eid, mon["next_check_at"])
                continue
            if check_at <= now:
                # Overdue — schedule 5 seconds from now to avoid immediate execution during startup
                self.schedule(eid, now + timedelta(seconds=5))
            else:
                self.schedule(eid, check_at)
            count += 1
        logger.info("Restored %d watch jobs from DB", count)
        return count


def _execute_recheck(market_id: str, db, config=None, watch_scheduler=None) -> None:
    """Job function called by APScheduler. Runs recheck and re-schedules if continuing watch."""
    from scanner.daemon.recheck import recheck_market

    logger.info("Executing scheduled recheck for %s", market_id)
    try:
        # Build a ScanService for full AI analysis
        service = None
        if config is not None:
            from scanner.tui.service import ScanService
            service = ScanService(config)

        result = recheck_market(
            market_id, db=service.db if service else db,
            service=service, trigger_source="scheduled",
        )
        logger.info("Recheck result for %s: %s", market_id, result.new_status)

        # Re-schedule if still WATCH with next_check_at
        if result.new_status == "watch" and result.next_check_at and watch_scheduler is not None:
            try:
                next_time = datetime.fromisoformat(result.next_check_at)
                watch_scheduler.schedule(market_id, next_time)
                logger.info("Re-scheduled %s for %s", market_id, result.next_check_at)
            except ValueError:
                logger.warning("Invalid next_check_at for %s: %s", market_id, result.next_check_at)
    except Exception:
        logger.exception("Recheck failed for %s", market_id)


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
    """Generate a macOS launchd plist for the scheduler daemon.

    Args:
        working_dir: Project root directory.
        python_path: Path to Python executable. Defaults to sys.executable.
    """
    import plistlib

    if python_path is None:
        python_path = sys.executable

    log_path = f"{working_dir}/data/scheduler.log"
    plist = {
        "Label": "com.polily.scheduler",
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


def run_daemon(db, config=None) -> None:
    """Daemon entry point: start scheduler, restore jobs, block until SIGTERM."""
    scheduler = WatchScheduler(db, config=config)
    scheduler.start()
    restored = scheduler.restore_from_db()

    # Initialize movement polling (poll_job alongside check_job)
    service_db = db
    if config is not None and config.movement.enabled:
        from scanner.daemon.poll_job import init_poller, restore_poll_jobs_from_db
        from scanner.tui.service import ScanService

        service = ScanService(config)
        service_db = service.db
        init_poller(scheduler.scheduler, config, service_db, service)
        poll_count = restore_poll_jobs_from_db(config, service_db)
        logger.info("Movement polling initialized: %d poll jobs", poll_count)

    logger.info("Daemon started with %d check jobs", restored)

    # Write PID file for SIGUSR1 notification
    import os
    pid_path = Path("data/scheduler.pid")
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
                logger.info("Reloading jobs from DB (SIGUSR1)")
                scheduler.restore_from_db()
                if config is not None and config.movement.enabled:
                    from scanner.daemon.poll_job import restore_poll_jobs_from_db
                    restore_poll_jobs_from_db(config, service_db)
    except AttributeError:
        # Windows doesn't have signal.pause
        import time
        while True:
            time.sleep(60)
