"""Toggle auto_monitor: register/remove poll + check jobs atomically."""

import logging
from datetime import UTC, datetime

from scanner.config import ScannerConfig
from scanner.db import PolilyDB
from scanner.market_state import get_market_state, set_market_state
from scanner.watch_poller_jobs import register_poll_job, remove_poll_job

logger = logging.getLogger(__name__)


def toggle_auto_monitor(
    market_id: str,
    *,
    enable: bool,
    db: PolilyDB,
    config: ScannerConfig,
) -> None:
    """Enable or disable auto monitoring for a market.

    Works on any active status (watch/buy_yes/buy_no). Rejected for pass/closed.
    """
    state = get_market_state(market_id, db)
    if not state:
        logger.warning("Cannot toggle auto_monitor: market %s not found", market_id)
        return

    if enable and state.status in ("closed", "pass"):
        logger.warning("Cannot enable auto_monitor: market %s is %s", market_id, state.status)
        return

    # Update state
    state.auto_monitor = enable
    state.updated_at = datetime.now(UTC).isoformat()
    set_market_state(market_id, state, db)

    if enable:
        register_poll_job(
            market_id=market_id,
            market_type=state.market_type or "other",
            token_id=state.clob_token_id_yes or "",
            config=config,
            db=db,
            market_title=state.title,
            condition_id=state.condition_id or "",
        )
        logger.info("Enabled auto_monitor for %s", market_id)
    else:
        remove_poll_job(market_id)
        logger.info("Disabled auto_monitor for %s", market_id)


def cleanup_closed_market(market_id: str) -> None:
    """Remove all jobs when a market is closed."""
    remove_poll_job(market_id)
