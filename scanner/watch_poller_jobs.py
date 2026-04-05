"""APScheduler job registration for price polling.

Each auto_monitor=True WATCH market gets:
  1. poll_job (IntervalTrigger) — lightweight movement detection
  2. check_job (DateTrigger) — AI analysis at next_check_at

This module handles poll_job lifecycle.
check_job is handled by watch_scheduler.py (from watch-lifecycle-plan).
"""

import logging
from dataclasses import dataclass
from typing import Any

from scanner.config import MovementConfig, ScannerConfig
from scanner.db import PolilyDB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollerContext:
    """Immutable context — swapped atomically to avoid thread-safety races."""
    scheduler: Any
    config: ScannerConfig
    db: PolilyDB
    service: Any


# Single atomic reference (set once on daemon startup via init_poller)
_ctx: PollerContext | None = None


def init_poller(scheduler, config, db, service):
    """Initialize module-level context. Called once on daemon startup."""
    global _ctx
    _ctx = PollerContext(scheduler=scheduler, config=config, db=db, service=service)


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

    from scanner.market_state import get_auto_monitor_watches

    watches = get_auto_monitor_watches(db)
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

    Two phases (each creates its own event loop via asyncio.run()):
    1. Async poll (price fetch + signal computation)
    2. Sync recheck_market (AI analysis + state transition) — only if triggered

    IMPORTANT: Phase 1's asyncio.run() completes and closes its loop before
    Phase 2 begins. Phase 2 creates a fresh loop. This is safe in CPython with
    APScheduler 3.x BackgroundScheduler (thread pool, no pre-existing loop).
    Do NOT migrate to AsyncIOScheduler without restructuring this flow.
    """
    import asyncio

    ctx = _ctx
    if ctx is None:
        logger.error("Poll job called before init_poller() — skipping")
        return

    config = ctx.config
    db = ctx.db

    try:
        from scanner.price_poller import PricePoller
        from scanner.market_state import get_market_state

        # Check market is still in WATCH state
        state = get_market_state(market_id, db)
        if not state or state.status != "watch":
            logger.info("Market %s no longer in WATCH — removing poll job", market_id)
            remove_poll_job(market_id)
            return

        prev_price = state.price_at_watch

        # Phase 1: async poll (price fetch + signal computation)
        # poll_and_close wraps poll + client cleanup in a single event loop
        # to avoid cross-loop RuntimeError on httpx transport close.
        poller = PricePoller(config=config, db=db)

        async def _poll_and_close():
            try:
                return await poller.poll_single(
                    market_id,
                    market_type=market_type,
                    token_id=token_id,
                    condition_id=condition_id,
                    prev_price=prev_price,
                    market_title=market_title,
                )
            finally:
                await poller.close()

        result = asyncio.run(_poll_and_close())

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
