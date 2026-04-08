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
                    from scanner.watch_recheck import _close_market
                    _close_market(market_id, state, db)
                    from scanner.auto_monitor import cleanup_closed_market
                    cleanup_closed_market(market_id)
                    logger.info("Market %s expired — closed and removed poll job", market_id)
                    return
            except ValueError:
                pass

        prev_price = state.price_at_watch

        # Fresh poller + client per poll — resilient to sleep/wake
        from scanner.price_poller import PricePoller

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
        from scanner.movement_store import get_recent_movements, get_today_analysis_count
        mc = config.movement

        # Cooldown check
        in_cooldown = False
        from datetime import UTC, datetime
        for e in get_recent_movements(market_id, db, hours=1):
            if e.get("triggered_analysis"):
                triggered_at = datetime.fromisoformat(e["created_at"])
                if triggered_at.tzinfo is None:
                    triggered_at = triggered_at.replace(tzinfo=UTC)
                if (datetime.now(UTC) - triggered_at).total_seconds() < result.cooldown_seconds:
                    in_cooldown = True
                    break

        at_daily_limit = get_today_analysis_count(market_id, db) >= mc.daily_analysis_limit

        if (result.should_trigger(mc.magnitude_threshold, mc.quality_threshold)
                and not in_cooldown
                and not at_daily_limit):

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
        # --- Drift detection (catches what M/Q misses) ---
        elif not at_daily_limit:
            from scanner.drift_detector import (
                CusumAccumulator,
                build_price_history,
                check_rolling_windows,
            )
            from scanner.movement_store import get_latest_movement

            # Rolling windows
            history = build_price_history(market_id, db)
            drift_windows = mc.drift_windows.get(market_type, mc.drift_windows.get("default", {}))
            current_price = result.signals.price_z_score  # not the actual price
            # Get actual current price from latest movement_log
            latest = get_latest_movement(market_id, db)
            current_price = latest["yes_price"] if latest and latest.get("yes_price") else 0

            window_alerts = check_rolling_windows(current_price, history, drift_windows)

            # CUSUM (tick-to-tick delta)
            if market_id not in _cusum_states:
                _cusum_states[market_id] = CusumAccumulator(
                    drift=mc.cusum_drift, threshold=mc.cusum_threshold)
                # Warm up from recent history on first encounter
                if len(history) >= 2:
                    sorted_hist = sorted(history, key=lambda x: x[0], reverse=True)
                    deltas = [sorted_hist[i][1] - sorted_hist[i + 1][1]
                              for i in range(len(sorted_hist) - 1)]
                    _cusum_states[market_id].warm_up(deltas)

            cusum_alerts = []
            if latest and latest.get("yes_price") is not None:
                ts = datetime.fromisoformat(latest["created_at"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                gap_seconds = (datetime.now(UTC) - ts).total_seconds()
                # Skip CUSUM for large gaps (sleep/wake) — rolling windows handle those
                if gap_seconds < 300 and prev_price is not None:
                    price_change = current_price - latest["yes_price"]
                    cusum_alerts = _cusum_states[market_id].update(price_change)

            drift_alerts = window_alerts + cusum_alerts
            if drift_alerts:
                # Drift-specific cooldown (longer than M/Q)
                drift_in_cooldown = False
                for e in get_recent_movements(market_id, db, hours=1):
                    if e.get("triggered_analysis"):
                        triggered_at = datetime.fromisoformat(e["created_at"])
                        if triggered_at.tzinfo is None:
                            triggered_at = triggered_at.replace(tzinfo=UTC)
                        if (datetime.now(UTC) - triggered_at).total_seconds() < mc.drift_cooldown_seconds:
                            drift_in_cooldown = True
                            break

                if not drift_in_cooldown:
                    # Mark + trigger
                    db.conn.execute(
                        """UPDATE movement_log SET triggered_analysis = 1
                        WHERE market_id = ? AND id = (
                            SELECT id FROM movement_log WHERE market_id = ?
                            ORDER BY id DESC LIMIT 1
                        )""", (market_id, market_id))
                    db.conn.commit()

                    from scanner.notifications import add_notification, send_desktop_notification
                    from scanner.watch_recheck import recheck_market
                    recheck_market(market_id, db=db, service=ctx.service, trigger_source="movement")
                    alert_info = drift_alerts[0]
                    title = f"漂移检测 [{alert_info['type']}]"
                    body = f"{market_title[:40]}: {alert_info.get('direction', '')} {alert_info.get('change', alert_info.get('cumulative', ''))}"
                    add_notification(db, title=title, body=body,
                                   market_id=market_id, trigger_source="movement",
                                   action_result=alert_info["type"])
                    send_desktop_notification(title, body)
                    logger.info("Drift triggered AI for %s: %s", market_id, alert_info)
                else:
                    logger.debug("Drift detected for %s but in cooldown", market_id)
            else:
                logger.debug("Poll %s: M=%.0f Q=%.0f [%s] — no trigger",
                             market_id, result.magnitude, result.quality, result.label)

    except Exception:
        logger.exception("Poll failed for %s — will retry next interval", market_id)
