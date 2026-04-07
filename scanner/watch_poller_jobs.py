"""APScheduler job registration for price polling.

Each auto_monitor=True WATCH market gets:
  1. poll_job (IntervalTrigger) — lightweight movement detection
  2. check_job (DateTrigger) — AI analysis at next_check_at

This module handles poll_job lifecycle.
check_job is handled by watch_scheduler.py (from watch-lifecycle-plan).
"""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from scanner.config import MovementConfig, ScannerConfig
from scanner.db import PolilyDB

logger = logging.getLogger(__name__)


@dataclass
class PollerContext:
    """Mutable context with persistent event loop and HTTP clients."""
    scheduler: Any
    config: ScannerConfig
    db: PolilyDB
    service: Any
    loop: asyncio.AbstractEventLoop | None = field(default=None, repr=False)
    _poller: Any = field(default=None, repr=False)  # PricePoller, lazy init

    def get_poller(self):
        """Lazily create a persistent PricePoller (reuses httpx client)."""
        if self._poller is None:
            from scanner.price_poller import PricePoller
            self._poller = PricePoller(config=self.config, db=self.db)
        return self._poller


# Single reference (set once on daemon startup via init_poller)
_ctx: PollerContext | None = None


def _start_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Run event loop forever in a background thread."""
    asyncio.set_event_loop(loop)
    loop.run_forever()


def init_poller(scheduler, config, db, service):
    """Initialize module-level context with persistent event loop."""
    global _ctx
    loop = asyncio.new_event_loop()
    _ctx = PollerContext(scheduler=scheduler, config=config, db=db, service=service, loop=loop)
    # Start persistent event loop in daemon thread
    t = threading.Thread(target=_start_event_loop, args=(loop,), daemon=True, name="poller-loop")
    t.start()
    logger.info("Persistent poller event loop started")


def get_poll_interval(market_type: str, movement_config: MovementConfig) -> int:
    """Get poll interval in seconds for a market type."""
    return movement_config.poll_intervals.get(
        market_type,
        movement_config.poll_intervals.get("default", 30),
    )


def register_poll_job(
    *,
    market_id: str,
    market_type: str,
    token_id: str,
    config: ScannerConfig,
    db: PolilyDB,
    market_title: str = "",
    condition_id: str = "",
) -> dict:
    """Register a poll job for a WATCH market. Returns job metadata dict."""
    interval = get_poll_interval(market_type, config.movement)
    job_id = f"poll_{market_id}"

    if _ctx is not None and _ctx.scheduler is not None:
        _ctx.scheduler.add_job(
            "scanner.watch_poller_jobs:_execute_poll",
            "interval",
            seconds=interval,
            id=job_id,
            replace_existing=True,
            kwargs={
                "market_id": market_id,
                "market_type": market_type,
                "token_id": token_id,
                "market_title": market_title,
                "condition_id": condition_id,
            },
            max_instances=1,
        )
        logger.info("Registered poll job %s (every %ds)", job_id, interval)

    return {
        "market_id": market_id,
        "job_id": job_id,
        "interval_seconds": interval,
        "market_type": market_type,
    }


def restore_poll_jobs_from_db(config: ScannerConfig, db: PolilyDB) -> int:
    """Restore poll jobs for all auto_monitor=True WATCH markets.

    Called once on daemon startup after init_poller().
    Also prunes stale movement_log entries.
    Returns number of jobs restored.
    """
    from scanner.movement_store import prune_old_movements
    pruned = prune_old_movements(db, days=7)
    if pruned > 0:
        logger.info("Pruned %d stale movement_log entries", pruned)

    from scanner.market_state import get_active_monitors

    watches = get_active_monitors(db)
    count = 0
    for market_id, state in watches.items():
        register_poll_job(
            market_id=market_id,
            market_type=state.market_type or "other",
            token_id=state.clob_token_id_yes or "",
            config=config,
            db=db,
            market_title=state.title,
            condition_id=state.condition_id or "",
        )
        count += 1
    logger.info("Restored %d poll jobs from DB", count)
    return count


def remove_poll_job(market_id: str) -> bool:
    """Remove the poll job for a market."""
    job_id = f"poll_{market_id}"
    if _ctx is not None and _ctx.scheduler is not None:
        try:
            _ctx.scheduler.remove_job(job_id)
            logger.info("Removed poll job %s", job_id)
            return True
        except Exception:
            return False
    return True  # no scheduler = nothing to remove


def _execute_poll(
    market_id: str,
    market_type: str,
    token_id: str,
    market_title: str = "",
    condition_id: str = "",
):
    """APScheduler callback: run a single poll cycle.

    Phase 1: submit async poll to persistent event loop (reuses httpx client)
    Phase 2: sync recheck_market if triggered (uses its own asyncio.run for AI)
    """
    ctx = _ctx
    if ctx is None:
        logger.error("Poll job called before init_poller() — skipping")
        return

    config = ctx.config
    db = ctx.db

    try:
        from scanner.market_state import get_market_state

        state = get_market_state(market_id, db)
        if not state or state.status in ("closed", "pass"):
            logger.info("Market %s is %s — removing poll job", market_id, state.status if state else "gone")
            remove_poll_job(market_id)
            return

        # Check if market has expired
        if state.resolution_time:
            from datetime import UTC, datetime
            try:
                res_time = datetime.fromisoformat(state.resolution_time)
                if res_time < datetime.now(UTC):
                    from scanner.watch_recheck import _close_market
                    _close_market(market_id, state, db)
                    from scanner.auto_monitor import cleanup_closed_market
                    cleanup_closed_market(market_id)
                    logger.info("Market %s expired — closed and removed poll job", market_id)
                    return
            except ValueError:
                pass

        prev_price = state.price_at_watch
        poller = ctx.get_poller()

        # Submit to persistent event loop — no new loop creation per poll
        future = asyncio.run_coroutine_threadsafe(
            poller.poll_single(
                market_id,
                market_type=market_type,
                token_id=token_id,
                condition_id=condition_id,
                prev_price=prev_price,
                market_title=market_title,
            ),
            ctx.loop,
        )
        result = future.result(timeout=30)

        # Check if should trigger AI
        mc = config.movement
        if (result.should_trigger(mc.magnitude_threshold, mc.quality_threshold)
                and not poller.check_cooldown(market_id, result.cooldown_seconds)
                and not poller.check_daily_limit(market_id)):

            # Mark the already-written movement_log entry as triggered
            db.conn.execute(
                """UPDATE movement_log SET triggered_analysis = 1
                WHERE market_id = ? AND id = (
                    SELECT id FROM movement_log WHERE market_id = ?
                    ORDER BY id DESC LIMIT 1
                )""",
                (market_id, market_id),
            )
            db.conn.commit()

            # Phase 2: sync recheck_market (uses its own asyncio.run() for AI)
            from scanner.watch_recheck import recheck_market
            recheck_market(market_id, db=db, service=ctx.service, trigger_source="movement")

            # Send movement-specific notification
            from scanner.notifications import add_notification, send_desktop_notification
            title = f"异动检测 [{result.label}]"
            body = f"{market_title[:40]}: M={result.magnitude:.0f} Q={result.quality:.0f}"
            add_notification(db, title=title, body=body,
                           market_id=market_id, trigger_source="movement",
                           action_result=result.label)
            send_desktop_notification(title, body)

            logger.info("Movement triggered AI for %s: M=%.0f Q=%.0f [%s]",
                        market_id, result.magnitude, result.quality, result.label)
        else:
            logger.debug("Poll %s: M=%.0f Q=%.0f [%s] — no trigger",
                         market_id, result.magnitude, result.quality, result.label)

    except Exception:
        logger.exception("Poll failed for %s — will retry next interval", market_id)
