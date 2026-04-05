"""Notify the scheduler daemon to reload jobs from DB."""

import logging
import os
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

PID_PATH = Path("data/scheduler.pid")


def notify_daemon() -> bool:
    """Send SIGUSR1 to daemon to reload jobs. Returns True if signal sent."""
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGUSR1)
        logger.info("Sent SIGUSR1 to daemon (pid=%d)", pid)
        return True
    except (OSError, ValueError):
        return False
