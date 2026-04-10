"""Toggle auto_monitor: register/remove poll + check jobs atomically.

TODO: v0.5.0 Task 3.6 — rewrite against event_monitors table.
Currently stubbed: market_states table was removed.
"""

import logging

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB

logger = logging.getLogger(__name__)


def toggle_auto_monitor(
    market_id: str,
    *,
    enable: bool,
    db: PolilyDB,
    config: ScannerConfig,
) -> None:
    """Enable or disable auto monitoring for a market.

    TODO: v0.5.0 — rewrite to use event_monitors instead of market_states.
    """
    # No-op stub — will be rewritten in Task 3.6
    logger.warning("toggle_auto_monitor is stubbed (v0.5.0 restructure)")


def cleanup_closed_market(market_id: str) -> None:
    """Remove all jobs when a market is closed."""
    from scanner.daemon.poll_job import remove_poll_job
    remove_poll_job(market_id)
