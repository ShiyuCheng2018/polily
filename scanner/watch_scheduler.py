"""APScheduler-based watch scheduler with MemoryJobStore.

Jobs are restored from market_states table on startup. No SQLAlchemy needed.
"""

import logging
import signal
import sys
from datetime import UTC, datetime, timedelta

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler

from scanner.market_state import get_auto_monitor_watches

logger = logging.getLogger(__name__)


class WatchScheduler:
    """Schedule watch rechecks at exact next_check_at times."""

    def __init__(self, db):
        self.db = db
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
            kwargs={"market_id": market_id, "db": self.db},
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
        """On startup, restore jobs from market_states table.

        Returns the number of jobs restored.
        """
        watches = get_auto_monitor_watches(self.db)
        now = datetime.now(UTC)
        count = 0
        for mid, state in watches.items():
            if not state.next_check_at:
                continue
            try:
                check_at = datetime.fromisoformat(state.next_check_at)
            except ValueError:
                logger.warning("Invalid next_check_at for %s: %s", mid, state.next_check_at)
                continue
            if check_at <= now:
                # Overdue — schedule 5 seconds from now to avoid immediate execution during startup
                self.schedule(mid, now + timedelta(seconds=5))
            else:
                self.schedule(mid, check_at)
            count += 1
        logger.info("Restored %d watch jobs from DB", count)
        return count


def _execute_recheck(market_id: str, db) -> None:
    """Job function called by APScheduler. Runs recheck and re-schedules if continuing watch."""
    from scanner.watch_recheck import recheck_market

    logger.info("Executing scheduled recheck for %s", market_id)
    try:
        result = recheck_market(market_id, db=db, trigger_source="scheduled")
        logger.info("Recheck result for %s: %s", market_id, result.new_status)
    except Exception:
        logger.exception("Recheck failed for %s", market_id)


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


def run_daemon(db) -> None:
    """Daemon entry point: start scheduler, restore jobs, block until SIGTERM."""
    scheduler = WatchScheduler(db)
    scheduler.start()
    restored = scheduler.restore_from_db()
    logger.info("Daemon started with %d jobs", restored)

    def handle_signal(signum, frame):
        logger.info("Received signal %d, shutting down", signum)
        scheduler.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Block until signal
    try:
        signal.pause()
    except AttributeError:
        # Windows doesn't have signal.pause
        import time
        while True:
            time.sleep(60)
