"""APScheduler job registration for price polling.

Each auto_monitor=True WATCH market gets:
  1. poll_job (IntervalTrigger) — lightweight movement detection
  2. check_job (DateTrigger) — AI analysis at next_check_at

This module handles poll_job lifecycle.
check_job is handled by watch_scheduler.py (from watch-lifecycle-plan).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from scanner.core.config import MovementConfig, ScannerConfig
from scanner.core.db import PolilyDB

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PollerContext:
    """Immutable context — swapped atomically to avoid thread-safety races."""
    scheduler: Any
    config: ScannerConfig
    db: PolilyDB
    service: Any


# Single reference (set once on daemon startup via init_poller)
_ctx: PollerContext | None = None


def init_poller(scheduler, config, db, service):
    """Initialize module-level context."""
    global _ctx
    _ctx = PollerContext(scheduler=scheduler, config=config, db=db, service=service)


# Per-market CUSUM accumulators (in-memory, lost on restart — warm_up restores)
_cusum_states: dict = {}


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
            "scanner.daemon.poll_job:_execute_poll",
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
    from scanner.monitor.store import prune_old_movements
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
    # Cleanup CUSUM state
    _cusum_states.pop(market_id, None)
    return True  # no scheduler = nothing to remove


def _is_in_cooldown(market_id: str, db, cooldown_seconds: int) -> bool:
    """Check if market is in cooldown period."""
    from datetime import UTC, datetime

    from scanner.monitor.store import get_recent_movements
    for e in get_recent_movements(market_id, db, hours=1):
        if e.get("triggered_analysis"):
            triggered_at = datetime.fromisoformat(e["created_at"])
            if triggered_at.tzinfo is None:
                triggered_at = triggered_at.replace(tzinfo=UTC)
            if (datetime.now(UTC) - triggered_at).total_seconds() < cooldown_seconds:
                return True
    return False


def _mark_triggered(market_id: str, db) -> None:
    """Mark the latest movement_log entry as triggered."""
    db.conn.execute(
        """UPDATE movement_log SET triggered_analysis = 1
        WHERE market_id = ? AND id = (
            SELECT id FROM movement_log WHERE market_id = ?
            ORDER BY id DESC LIMIT 1
        )""", (market_id, market_id))
    db.conn.commit()


def _trigger_recheck(market_id: str, db, ctx, market_title: str, alerts: list) -> None:
    """Trigger AI analysis and send notification."""
    from scanner.daemon.recheck import recheck_market
    from scanner.notifications import add_notification, send_desktop_notification

    recheck_market(market_id, db=db, service=ctx.service, trigger_source="movement")
    alert_info = alerts[0]
    alert_type = alert_info.get("type", "movement")
    title = f"异动检测 [{alert_type}]"
    body = f"{market_title[:40]}: {alert_info.get('direction', '')} {alert_info.get('change', alert_info.get('cumulative', ''))}"
    add_notification(db, title=title, body=body,
                   market_id=market_id, trigger_source="movement",
                   action_result=alert_type)
    send_desktop_notification(title, body)
    logger.info("Triggered AI for %s: %s", market_id, alert_info)


def _execute_poll(
    market_id: str,
    market_type: str,
    token_id: str,
    market_title: str = "",
    condition_id: str = "",
):
    """APScheduler callback: run a single poll cycle.

    Each poll creates a fresh PricePoller + httpx client via asyncio.run().
    This avoids stale connections after macOS sleep/wake cycles.
    Phase 2 (AI recheck) uses its own asyncio.run() — safe because Phase 1
    completes and closes its loop before Phase 2 begins.
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
                    from scanner.daemon.recheck import _close_market
                    _close_market(market_id, state, db)
                    from scanner.daemon.auto_monitor import cleanup_closed_market
                    cleanup_closed_market(market_id)
                    logger.info("Market %s expired — closed and removed poll job", market_id)
                    return
            except ValueError:
                pass

        prev_price = state.price_at_watch

        # Fresh poller + client per poll — resilient to sleep/wake
        from scanner.monitor.poll import PricePoller

        async def _poll_and_close():
            poller = PricePoller(config=config, db=db)
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
        from scanner.monitor.store import get_recent_movements, get_today_analysis_count
        mc = config.movement
        from datetime import UTC, datetime

        in_cooldown = _is_in_cooldown(market_id, db, result.cooldown_seconds)
        at_daily_limit = get_today_analysis_count(market_id, db) >= mc.daily_analysis_limit

        if (result.should_trigger(mc.magnitude_threshold, mc.quality_threshold)
                and not in_cooldown
                and not at_daily_limit):

            _mark_triggered(market_id, db)
            _trigger_recheck(market_id, db, ctx, market_title,
                           [{"type": result.label, "direction": "", "change": result.magnitude}])
        # --- Drift detection (catches what M/Q misses) ---
        elif not at_daily_limit:
            from scanner.monitor.drift import (
                CusumAccumulator,
                build_price_history,
                check_rolling_windows,
            )
            # Get current price + previous price from movement_log
            recent = get_recent_movements(market_id, db, hours=1)
            if len(recent) < 2:
                # Not enough data for drift detection yet
                logger.debug("Poll %s: M=%.0f Q=%.0f [%s] — no trigger",
                             market_id, result.magnitude, result.quality, result.label)
            else:
                current_entry = recent[0]  # most recent (just written by poll_single)
                prev_entry = recent[1]     # previous poll
                current_price = current_entry.get("yes_price", 0)
                prev_poll_price = prev_entry.get("yes_price", 0)

                if current_price <= 0:
                    logger.debug("Poll %s: no valid price for drift detection", market_id)
                else:
                    # Rolling windows
                    history = build_price_history(market_id, db)
                    drift_windows = mc.drift_windows.get(market_type, mc.drift_windows.get("default", {}))
                    window_alerts = check_rolling_windows(current_price, history, drift_windows)

                    # CUSUM (tick-to-tick delta)
                    if market_id not in _cusum_states:
                        _cusum_states[market_id] = CusumAccumulator(
                            drift=mc.cusum_drift, threshold=mc.cusum_threshold)
                        # Warm up: replay deltas in chronological order (oldest→newest)
                        if len(history) >= 2:
                            chrono = sorted(history, key=lambda x: x[0], reverse=True)  # oldest first
                            deltas = [chrono[i + 1][1] - chrono[i][1] for i in range(len(chrono) - 1)]
                            _cusum_states[market_id].warm_up(deltas)

                    cusum_alerts = []
                    # Gap detection: time between previous and current poll
                    prev_ts = datetime.fromisoformat(prev_entry["created_at"])
                    if prev_ts.tzinfo is None:
                        prev_ts = prev_ts.replace(tzinfo=UTC)
                    gap_seconds = (datetime.now(UTC) - prev_ts).total_seconds()
                    if gap_seconds < 300 and prev_poll_price > 0:
                        # Normal tick — feed delta to CUSUM
                        price_change = current_price - prev_poll_price
                        cusum_alerts = _cusum_states[market_id].update(price_change)
                    # If gap > 5min (sleep/wake), rolling windows handle it, CUSUM skips

                    drift_alerts = window_alerts + cusum_alerts
                    if drift_alerts:
                        if not _is_in_cooldown(market_id, db, mc.drift_cooldown_seconds):
                            _mark_triggered(market_id, db)
                            _trigger_recheck(market_id, db, ctx, market_title, drift_alerts)
                        else:
                            logger.debug("Drift detected for %s but in cooldown", market_id)
                    else:
                        logger.debug("Poll %s: M=%.0f Q=%.0f [%s] — no drift",
                                     market_id, result.magnitude, result.quality, result.label)

    except Exception:
        logger.exception("Poll failed for %s — will retry next interval", market_id)
