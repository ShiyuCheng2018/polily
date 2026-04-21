"""ScanService v0.5.0: DB-first, event-level bridge between TUI and backend."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scanner.agents.narrative_writer import NarrativeWriterAgent
from scanner.analysis_store import AnalysisVersion, append_analysis, get_event_analyses
from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.events import (
    EventBus,
    TOPIC_MONITOR_UPDATED,
    TOPIC_POSITION_UPDATED,
    TOPIC_SCAN_UPDATED,
    TOPIC_WALLET_UPDATED,
    get_event_bus,
)
from scanner.core.event_store import (
    EventRow,
    get_event,
    get_event_markets,
)
from scanner.core.monitor_store import get_event_monitor
from scanner.core.positions import PositionManager
from scanner.core.trade_engine import TradeEngine
from scanner.core.wallet import WalletService
from scanner.daemon.auto_monitor import toggle_auto_monitor
from scanner.monitor.store import get_event_movements
from scanner.scan_log import (
    ScanLogEntry,
    ScanStepRecord,
    create_log_entry,
    finish_log_entry,
    load_scan_logs,
    save_scan_log,
)
from scanner.tui.views.scan_log import StepInfo

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def _validate_next_check_at(value: str | None) -> str | None:
    """Return value if it parses as ISO 8601 and is strictly in the future.

    Rejects: None, empty string, malformed date, past timestamps.
    Logs a warning on reject so bad agent output is observable.
    """
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        if parsed <= datetime.now(UTC):
            logger.warning("Agent emitted non-future next_check_at: %s", value)
            return None
        return value
    except (ValueError, TypeError):
        logger.warning("Agent emitted malformed next_check_at: %r", value)
        return None


class AnalysisInProgressError(Exception):
    """Raised when the user tries to start a second concurrent analysis
    for an event that already has a running scan_logs row.

    Invariant: at most one active (running) scan_logs row per event_id.
    """


class ActivePositionsError(Exception):
    """Raised when an operation would orphan open positions (e.g. disabling
    monitor on an event the user still holds shares in)."""


class MonitorRequiredError(Exception):
    """Raised by `ScanService.execute_buy / execute_sell` when the target
    event has `auto_monitor` off.

    Positions on an unmonitored event would silently rot (no price
    polling, no movement scoring, no narrator attention). `toggle_monitor`
    already blocks disabling monitor when positions exist (see
    `ActivePositionsError`), so by invariant sell should never hit an
    unmonitored event — a raise here on sell surfaces DB drift rather
    than trading against stale state.

    Policy lives in the service layer (not `TradeEngine`) so the engine
    stays a pure atomic primitive. Any future caller (e.g. a live-money
    trading service) MUST replicate this guard — wire it via service
    methods, not direct engine calls.
    """

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(
            f"Event {event_id} has monitoring disabled; enable it before trading",
        )


class ScanService:
    """DB-first bridge between TUI views, scan pipeline, AI agent, and DB."""

    def __init__(
        self,
        config: ScannerConfig | None = None,
        db: PolilyDB | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config or self._load_default_config()
        self.db = db or PolilyDB(self.config.archiving.db_file)

        # v0.6.0 wallet system: single dependency point for TUI views
        # (wallet.py / trade_dialog.py / paper_status.py)
        self.wallet = WalletService(self.db)
        self.positions = PositionManager(self.db)
        self.trade_engine = TradeEngine(self.db, self.wallet, self.positions)

        # Progress tracking for TUI
        self.on_progress: Callable[[list[StepInfo]], None] | None = None
        self.total_scanned: int = 0
        self.last_scan_id: str | None = None
        self._steps: list[StepInfo] = []
        self._current_log: ScanLogEntry | None = None
        self._current_narrator: NarrativeWriterAgent | None = None

        # v0.8.0 event bus: publish mutations to subscribed TUI views
        self.event_bus = event_bus or get_event_bus()

    @staticmethod
    def _load_default_config() -> ScannerConfig:
        minimal = Path("config.minimal.yaml")
        example = Path("config.example.yaml")
        if minimal.exists() and example.exists():
            return load_config(minimal, defaults_path=example)
        if example.exists():
            return load_config(example)
        return ScannerConfig()

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Add single event
    # ------------------------------------------------------------------

    async def add_event_by_url(self, url: str) -> dict | None:
        """Add a single event by Polymarket URL. Fetch, score, persist, log."""
        from scanner.scan.pipeline import fetch_and_score_event
        from scanner.url_parser import parse_polymarket_url

        slug = parse_polymarket_url(url)
        if not slug:
            return None

        self._steps = []
        self._current_log = create_log_entry(log_type="add_event")
        self._persist_log(self._current_log)

        try:
            result = await fetch_and_score_event(
                slug, config=self.config, db=self.db,
                progress_cb=self._on_pipeline_progress,
            )
        except Exception as e:
            self._finish_log("failed", error=str(e))
            raise

        if result is None:
            self._finish_log("failed", error="事件未找到")
            return None

        event_id = result["event"].event_id
        self._current_log.market_title = result["event"].title[:60]
        self._current_log.event_id = event_id

        # Upsert: remove old add_event record for this event
        self.db.conn.execute(
            "DELETE FROM scan_logs WHERE type = 'add_event' AND event_id = ? AND scan_id != ?",
            (event_id, self._current_log.scan_id),
        )
        self.db.conn.commit()

        self._finish_log("completed")
        return result

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_event(
        self,
        event_id: str,
        trigger_source: str = "manual",
        on_heartbeat: Callable[[float, str], None] | None = None,
        scan_id: str | None = None,
    ) -> AnalysisVersion:
        """Run AI analysis on an event. Writes full scan_logs lifecycle.

        Args:
            scan_id: If provided, this is a dispatcher-claimed pending row
                being executed (status already 'running'). If None, a fresh
                'running' row is inserted here (manual trigger from TUI).
        """
        from scanner.agents import narrator_registry
        from scanner.scan_log import (
            _make_scan_id,
            finish_scan,
            insert_pending_scan,
            supersede_pending_for_event,
        )

        event = get_event(event_id, self.db)
        if event is None:
            raise ValueError(f"Event {event_id} not found in DB")
        markets = get_event_markets(event_id, self.db)
        start_time = time.time()

        # --- Write the 'running' scan_log row ---
        # Invariant: at most one running row per event. Dispatcher-supplied
        # scan_id means the row is already running (atomically claimed by
        # `claim_pending_scan`), so the guard applies only to manual triggers.
        now_iso = datetime.now(UTC).isoformat()
        if scan_id is None:
            scan_id = _make_scan_id(prefix="r")
            # Atomic "insert only if no running row exists for this event":
            # INSERT ... SELECT ... WHERE NOT EXISTS evaluates within one
            # statement, so two concurrent callers can't both slip through.
            cur = self.db.conn.execute(
                "INSERT INTO scan_logs(scan_id, type, event_id, market_title, "
                "started_at, status, trigger_source) "
                "SELECT ?, 'analyze', ?, ?, ?, 'running', ? "
                "WHERE NOT EXISTS (SELECT 1 FROM scan_logs "
                "                  WHERE event_id=? AND status='running')",
                (scan_id, event_id, event.title, now_iso, trigger_source, event_id),
            )
            self.db.conn.commit()
            if cur.rowcount == 0:
                raise AnalysisInProgressError(
                    "该事件已有分析在进行中，请等待完成或先取消后再试",
                )

        has_position, position_summary = self._compute_position_context(event_id)
        existing = get_event_analyses(event_id, self.db)
        new_version_num = (existing[-1].version if existing else 0) + 1

        narrator = NarrativeWriterAgent(self.config.ai.narrative_writer)
        self._current_narrator = narrator
        narrator_registry.register(scan_id, narrator)
        agent_error: Exception | None = None
        narrative_output = None
        try:
            narrative_output = await narrator.generate(
                event_id=event_id,
                has_position=has_position,
                position_summary=position_summary,
                on_heartbeat=on_heartbeat,
                event_title=event.title,
            )
        except Exception as e:
            agent_error = e
        finally:
            self._current_narrator = None
            narrator_registry.unregister(scan_id)

        if agent_error is not None:
            logger.error(
                "narrator failed for scan_id=%s event_id=%s: %s",
                scan_id, event_id, agent_error,
                exc_info=agent_error,
            )
            try:
                finish_scan(
                    scan_id,
                    status="failed",
                    error=f"{type(agent_error).__name__}: {agent_error}"[:200],
                    db=self.db,
                )
                self.publish_scan_update(scan_id, event_id=event_id, status="failed")
            except Exception:
                logger.exception("finish_scan failed while recording agent error")
            raise agent_error

        # --- Build (don't persist yet) the analysis version ---
        # Persistence is gated on the atomic finish_scan UPDATE below: if
        # another writer (e.g. user cancel) already finalized the row, we
        # discard the narrator's output entirely so the cancelled scan
        # doesn't surface as a fresh entry in the event's history.
        prices_snapshot = {
            mr.market_id: {"yes": mr.yes_price, "no": mr.no_price} for mr in markets
        }
        version = AnalysisVersion(
            version=new_version_num,
            created_at=datetime.now(UTC).isoformat(),
            prices_snapshot=prices_snapshot,
            narrative_output=narrative_output.model_dump(),
            trigger_source=trigger_source,
            structure_score=event.structure_score,
            mispricing_signal="none",
            elapsed_seconds=time.time() - start_time,
        )

        # --- Atomic "claim the completion" ---
        # finish_scan UPDATE ... WHERE status='running' is the serialization
        # point. rowcount=1 → we won, safe to persist; rowcount=0 → someone
        # else finalized first (user cancel / crash / duplicate dispatch) →
        # the analysis is moot, do nothing else.
        if finish_scan(scan_id, status="completed", db=self.db) == 0:
            logger.info(
                "Analysis %s was finalized externally (likely cancelled) "
                "during narrator run; discarding narrator output",
                scan_id,
            )
            return version
        self.publish_scan_update(scan_id, event_id=event_id, status="completed")

        # Row flipped running→completed atomically. Now safe to persist.
        append_analysis(event_id, version, self.db)

        # --- Validate + emit next pending ---
        next_check = _validate_next_check_at(narrative_output.next_check_at)
        if next_check:
            supersede_pending_for_event(event_id, self.db)
            insert_pending_scan(
                event_id=event_id,
                event_title=event.title,
                scheduled_at=next_check,
                trigger_source="scheduled",
                scheduled_reason=(narrative_output.next_check_reason or "").strip() or None,
                db=self.db,
            )
        return version

    def cancel_analysis(self) -> None:
        """Cancel the currently running AI analysis."""
        narrator = self._current_narrator
        if narrator:
            narrator.cancel()
            logger.info("Analysis cancelled by user")

    def cancel_running_scan(self, scan_id: str) -> bool:
        """Cancel a running scan_logs row: kill narrator + mark row cancelled.

        Routes to narrator_registry so scans running under the dispatcher
        (different ScanService instance) are reachable.

        Returns True when the row was running and got flipped to cancelled;
        False when the row wasn't running (already done / superseded / gone).
        """
        from scanner.agents import narrator_registry
        from scanner.scan_log import finish_scan

        row = self.db.conn.execute(
            "SELECT status FROM scan_logs WHERE scan_id=?", (scan_id,),
        ).fetchone()
        if row is None or row["status"] != "running":
            return False
        # Best-effort kill via registry. A miss just means the narrator already
        # finished between SELECT above and here — we still mark cancelled.
        narrator_registry.cancel(scan_id)
        finish_scan(scan_id, status="cancelled", error=None, db=self.db)
        return True

    # ------------------------------------------------------------------
    # Event reads
    # ------------------------------------------------------------------

    def get_all_events(self) -> list[dict]:
        """Return all non-closed events, sorted by score desc."""
        return self._query_events("WHERE e.closed = 0")

    def _query_events(self, where_clause: str) -> list[dict]:
        """Query events with summary fields.

        SAFETY: where_clause must be a hardcoded string, never user input.
        """
        sql = f"""
            SELECT e.*,
                   COUNT(DISTINCT mk.market_id) AS market_count,
                   COALESCE(em.auto_monitor, 0) AS is_monitored,
                   pend.next_check_at AS next_check_at,
                   COUNT(DISTINCT ps.market_id || '/' || ps.side) AS position_count,
                   leader.group_item_title AS leader_title,
                   leader.yes_price AS leader_price,
                   COALESCE(ac.analysis_count, 0) AS analysis_count,
                   MIN(CASE WHEN mk.closed = 0 THEN mk.end_date END) AS markets_end_min,
                   MAX(CASE WHEN mk.closed = 0 THEN mk.end_date END) AS markets_end_max
            FROM events e
            LEFT JOIN markets mk ON mk.event_id = e.event_id
            LEFT JOIN event_monitors em ON em.event_id = e.event_id
            LEFT JOIN positions ps ON ps.event_id = e.event_id
            LEFT JOIN (
                SELECT event_id, MIN(scheduled_at) AS next_check_at
                FROM scan_logs
                WHERE status = 'pending'
                GROUP BY event_id
            ) pend ON pend.event_id = e.event_id
            LEFT JOIN (
                SELECT m1.event_id, m1.group_item_title, m1.yes_price
                FROM markets m1
                INNER JOIN (
                    SELECT event_id, MAX(yes_price) AS max_price
                    FROM markets
                    GROUP BY event_id
                ) m2 ON m1.event_id = m2.event_id AND m1.yes_price = m2.max_price
                GROUP BY m1.event_id
            ) leader ON leader.event_id = e.event_id
            LEFT JOIN (
                SELECT event_id, COUNT(*) AS analysis_count
                FROM analyses
                GROUP BY event_id
            ) ac ON ac.event_id = e.event_id
            {where_clause}
            GROUP BY e.event_id
            ORDER BY COALESCE(e.structure_score, 0) DESC
        """
        rows = self.db.conn.execute(sql).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            event = EventRow(**{
                k: d[k] for k in EventRow.model_fields if k in d
            })
            is_monitored = bool(d["is_monitored"])
            results.append({
                "event": event,
                "market_count": d["market_count"],
                "is_monitored": is_monitored,
                "has_position": d["position_count"] > 0,
                "leader_title": d.get("leader_title"),
                "leader_price": d.get("leader_price"),
                "next_check_at": d.get("next_check_at"),
                "analysis_count": d["analysis_count"],
                "markets_end_min": d.get("markets_end_min"),
                "markets_end_max": d.get("markets_end_max"),
                "movement": self._fetch_movement(event.event_id) if is_monitored else None,
            })
        return results

    def get_archived_events(self) -> list[dict]:
        """Events the user was monitoring at the moment they closed.

        Source-of-truth for the Archive view (menu 5). Filter is two-part:
        `events.closed=1` (the event finished) AND
        `event_monitors.auto_monitor=1` (the user was monitoring).

        The auto_monitor flag is preserved through close (by design — it's a
        user-intent flag, see PR #40), so the value at query time == value at
        close time for any event not explicitly toggled off post-close.
        """
        # NOTE: aliased to `markets_total` (not `market_count`) because
        # `events.market_count` is a real column pulled in via `e.*`; duplicate
        # keys on sqlite3.Row collapse to the first occurrence on dict(row).
        sql = """
            SELECT e.*,
                   COUNT(DISTINCT mk.market_id) AS markets_total
            FROM events e
            INNER JOIN event_monitors em ON em.event_id = e.event_id
            LEFT JOIN markets mk ON mk.event_id = e.event_id
            WHERE e.closed = 1 AND em.auto_monitor = 1
            GROUP BY e.event_id
            ORDER BY e.updated_at DESC
        """
        rows = self.db.conn.execute(sql).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            event = EventRow(**{k: d[k] for k in EventRow.model_fields if k in d})
            results.append({
                "event": event,
                "market_count": d["markets_total"],
            })
        return results

    def _fetch_movement(self, event_id: str) -> dict | None:
        """Roll up the latest movement tick for a monitored event.

        Uses the same aggregation as `movement_sparkline.get_event_movement`
        (latest tick's max-M/max-Q with label from strongest sub-market),
        which correctly skips the event-level aggregate rows that poll_job
        writes with market_id=NULL. Returns None when no movement rows exist
        in the last hour so the UI can show a dash.
        """
        from scanner.monitor.store import get_event_movements
        from scanner.tui.components.movement_sparkline import get_event_movement

        movements = get_event_movements(event_id, self.db, hours=1)
        if not movements:
            return None
        m, q, label = get_event_movement(movements)
        return {"label": label, "magnitude": float(m), "quality": float(q)}

    def get_event_detail(self, event_id: str) -> dict | None:
        """Return full detail for an event: event, markets, analyses, trades, monitor, movements.

        `trades` is derived from the v0.6.0 `positions` table, reshaped into
        the PositionPanel schema (market_id/side/title/entry_price/
        position_size_usd). Previously this read the legacy `paper_trades`
        table, which TradeEngine stopped writing in v0.6.0 — causing
        EventDetailView to show "无持仓" for live positions.
        """
        from scanner.core.positions import is_dust_position

        event = get_event(event_id, self.db)
        if event is None:
            return None
        markets = get_event_markets(event_id, self.db)
        analyses = get_event_analyses(event_id, self.db)
        _positions = self.positions.get_event_positions(event_id)
        # Filter dust from the display-facing trades list. Accounting
        # (_compute_position_context, get_event_position_count) keeps
        # raw rows via `self.positions.get_event_positions(...)`.
        trades = [
            {
                "market_id": p["market_id"],
                "side": p["side"],
                "title": p.get("title") or "",
                "entry_price": p["avg_cost"],
                "position_size_usd": p["cost_basis"],
            }
            for p in _positions
            if not is_dust_position(p)
        ]
        monitor = get_event_monitor(event_id, self.db)
        movements = get_event_movements(event_id, self.db, hours=24)
        return {
            "event": event,
            "markets": markets,
            "analyses": analyses,
            "trades": trades,
            "monitor": monitor,
            "movements": movements,
        }

    # ------------------------------------------------------------------
    # Monitor
    # ------------------------------------------------------------------

    def get_monitor_count(self) -> int:
        """Count events with auto_monitor enabled."""
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM event_monitors WHERE auto_monitor = 1",
        ).fetchone()
        return row[0] if row else 0

    def is_event_monitored(self, event_id: str) -> bool:
        """Check if an event has auto_monitor enabled."""
        mon = get_event_monitor(event_id, self.db)
        return bool(mon and mon.get("auto_monitor"))

    # ------------------------------------------------------------------
    # Positions (v0.6.0) — legacy "paper trades" API name retained where
    # TUI views read a shimmed dict shape.
    # ------------------------------------------------------------------

    def _compute_position_context(
        self, event_id: str,
    ) -> tuple[bool, str | None]:
        """Return (has_position, summary) for the NarrativeWriter prompt.

        Sourced from `positions` (the v0.6.0 write target). Format keeps
        the line layout the agent prompt expects so no prompt change is
        needed: ``SIDE @ avg_cost  $cost_basis  market_id  title``.
        """
        rows = self.positions.get_event_positions(event_id)
        if not rows:
            return False, None
        lines = []
        for p in rows:
            side = (p.get("side") or "?").upper()
            entry = p.get("avg_cost") or 0
            size = p.get("cost_basis") or 0
            mid = p.get("market_id") or "?"
            title = (p.get("title") or "")[:40]
            lines.append(f"{side} @ {entry:.2f}  ${size:.0f}  {mid}  {title}")
        return True, "\n".join(lines)

    def get_open_trades(self) -> list[dict]:
        """Open positions in paper_trades dict shape (shim for legacy TUI views).

        Source of truth is `positions` post-v0.6.0. Synthetic `id` preserves
        the DataTable row_key logic in paper_status.py. Callers needing the
        native position shape should use `get_all_positions` instead.

        Dust positions (`shares < DUST_SHARE_THRESHOLD`) are filtered out so
        `paper_status` doesn't display 0.02-share stragglers that partial
        sells leave behind. Accounting layers still see them via
        `self.positions.get_all_positions()`.
        """
        from scanner.core.positions import is_dust_position

        positions = self.positions.get_all_positions()
        return [
            {
                "id": f"{p['market_id']}:{p['side']}",
                "market_id": p["market_id"],
                "event_id": p["event_id"],
                "side": p["side"],
                "title": p["title"],
                "entry_price": p["avg_cost"],
                "position_size_usd": p["cost_basis"],
            }
            for p in positions
            if not is_dust_position(p)
        ]

    # ------------------------------------------------------------------
    # Realized P&L history (v0.6.0 — sourced from wallet_transactions)
    # ------------------------------------------------------------------

    def get_realized_history(self) -> list[dict]:
        """Return SELL + RESOLVE rows with matched FEE and market title.

        Each returned dict carries the ledger fields plus:
          * ``title`` — markets.question (for UI display)
          * ``fee_usd`` — sum of FEE rows on the same (market_id, side)
            within a 2-second window of the realize event (same txn id
            neighbourhood in practice)

        Ordered newest-first by created_at.
        """
        cur = self.db.conn.execute(
            """
            SELECT
                w.id,
                w.created_at,
                w.type,
                w.market_id,
                w.event_id,
                w.side,
                w.shares,
                w.price,
                w.amount_usd,
                w.realized_pnl,
                COALESCE(m.question, '') AS title,
                CASE WHEN w.type = 'SELL' THEN (
                    SELECT COALESCE(SUM(-f.amount_usd), 0)
                    FROM wallet_transactions f
                    WHERE f.type = 'FEE'
                      AND f.market_id = w.market_id
                      AND f.side = w.side
                      AND f.notes LIKE '%SELL%'
                      AND ABS(julianday(f.created_at) - julianday(w.created_at))
                          < 2.0 / 86400.0
                ) ELSE 0 END AS fee_usd
            FROM wallet_transactions w
            LEFT JOIN markets m ON m.market_id = w.market_id
            WHERE w.type IN ('SELL', 'RESOLVE')
            ORDER BY w.id DESC
            """,
        )
        return [dict(r) for r in cur.fetchall()]

    def get_realized_summary(self) -> dict:
        """Aggregate for the history page header.

        count — number of realize events (SELL + RESOLVE rows)
        total_pnl — SUM(realized_pnl) over SELL + RESOLVE
        total_fees — SUM(-amount_usd) over FEE rows (all-time scope: every
            fee the user paid; matches the pattern shown inline per row)
        """
        row = self.db.conn.execute(
            """
            SELECT
                COUNT(*) FILTER (WHERE type IN ('SELL', 'RESOLVE')) AS count,
                COALESCE(
                    SUM(realized_pnl) FILTER (WHERE type IN ('SELL', 'RESOLVE')),
                    0.0
                ) AS total_pnl,
                COALESCE(
                    SUM(-amount_usd) FILTER (WHERE type = 'FEE'),
                    0.0
                ) AS total_fees
            FROM wallet_transactions
            """,
        ).fetchone()
        return {
            "count": row["count"],
            "total_pnl": row["total_pnl"],
            "total_fees": row["total_fees"],
        }

    # ------------------------------------------------------------------
    # Wallet / positions / trade proxies (v0.6.0)
    # ------------------------------------------------------------------

    def _assert_monitor_active_for_market(self, market_id: str) -> None:
        """Raise `MonitorRequiredError` when the market's owning event has
        `auto_monitor` off or no monitor row. Policy guard in front of
        every trade so autopilot / external callers inherit the check.
        """
        row = self.db.conn.execute(
            "SELECT em.auto_monitor FROM markets m "
            "LEFT JOIN event_monitors em ON em.event_id = m.event_id "
            "WHERE m.market_id = ?",
            (market_id,),
        ).fetchone()
        if row is None:
            # Market doesn't exist — let downstream raise a more specific error.
            return
        if not row["auto_monitor"]:
            event_row = self.db.conn.execute(
                "SELECT event_id FROM markets WHERE market_id = ?",
                (market_id,),
            ).fetchone()
            raise MonitorRequiredError(event_row["event_id"])

    def execute_buy(self, *, market_id: str, side: str, shares: float) -> dict:
        self._assert_monitor_active_for_market(market_id)
        result = self.trade_engine.execute_buy(
            market_id=market_id, side=side, shares=shares,
        )
        # v0.8.0: let wallet / paper_status / event_detail views refresh
        # without waiting for the next heartbeat.
        self.event_bus.publish(
            TOPIC_POSITION_UPDATED,
            {"market_id": market_id, "side": side, "size": shares, "source": "buy"},
        )
        self.event_bus.publish(
            TOPIC_WALLET_UPDATED,
            {"balance": self.wallet.get_cash(), "source": "buy"},
        )
        return result

    def execute_sell(self, *, market_id: str, side: str, shares: float) -> dict:
        self._assert_monitor_active_for_market(market_id)
        result = self.trade_engine.execute_sell(
            market_id=market_id, side=side, shares=shares,
        )
        self.event_bus.publish(
            TOPIC_POSITION_UPDATED,
            {"market_id": market_id, "side": side, "size": shares, "source": "sell"},
        )
        self.event_bus.publish(
            TOPIC_WALLET_UPDATED,
            {"balance": self.wallet.get_cash(), "source": "sell"},
        )
        return result

    def topup(self, amount: float) -> None:
        self.wallet.topup(amount)
        self.event_bus.publish(
            TOPIC_WALLET_UPDATED,
            {"balance": self.wallet.get_cash(), "source": "topup", "amount": amount},
        )

    def withdraw(self, amount: float) -> None:
        self.wallet.withdraw(amount)
        self.event_bus.publish(
            TOPIC_WALLET_UPDATED,
            {"balance": self.wallet.get_cash(), "source": "withdraw", "amount": amount},
        )

    def publish_scan_update(self, scan_id: str, *, event_id: str, status: str) -> None:
        """v0.8.0: publish TOPIC_SCAN_UPDATED. Called from analyze_event after finish_scan."""
        self.event_bus.publish(
            TOPIC_SCAN_UPDATED,
            {"scan_id": scan_id, "event_id": event_id, "status": status},
        )

    def get_wallet_snapshot(self) -> dict:
        return self.wallet.get_snapshot()

    def get_wallet_transactions(self, limit: int = 100) -> list[dict]:
        return self.wallet.list_transactions(limit=limit)

    def get_all_positions(self) -> list[dict]:
        """Display-layer positions, with dust (`shares < DUST_SHARE_THRESHOLD`)
        filtered. Use `self.positions.get_all_positions()` for accounting
        where dust must still count (trade engine, narrator prompt).
        """
        from scanner.core.positions import is_dust_position
        return [
            p for p in self.positions.get_all_positions()
            if not is_dust_position(p)
        ]

    def get_event_positions(self, event_id: str) -> list[dict]:
        return self.positions.get_event_positions(event_id)

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def pass_event(self, event_id: str) -> None:
        """Mark an event as passed by the user."""
        self.db.conn.execute(
            "UPDATE events SET user_status = 'pass' WHERE event_id = ?",
            (event_id,),
        )
        self.db.conn.commit()

    def toggle_monitor(self, event_id: str, enable: bool) -> None:
        """Enable or disable monitoring for an event.

        Disabling is blocked when the event has open positions — closing
        monitor stops polling, which stops auto-resolution, which would
        silently orphan the user's skin in the game. Callers should check
        `get_event_position_count` first to surface a UI-friendly error.

        v0.7.0: Disabling also supersedes any pending scheduled analysis
        for the event (Q3 decision). Re-enabling does NOT restore them —
        the user can manually trigger a fresh analysis if they want.
        """
        if not enable and self.get_event_position_count(event_id) > 0:
            raise ActivePositionsError(
                f"Cannot disable monitoring — event {event_id} has open positions",
            )
        toggle_auto_monitor(event_id, enable=enable, db=self.db)
        if not enable:
            from scanner.scan_log import supersede_pending_for_event
            supersede_pending_for_event(event_id, self.db)
        # v0.8.0: let monitor_list / event_detail refresh immediately.
        self.event_bus.publish(
            TOPIC_MONITOR_UPDATED,
            {"event_id": event_id, "auto_monitor": enable},
        )

    def get_event_position_count(self, event_id: str) -> int:
        """Count open positions across every market in the event."""
        return len(self.positions.get_event_positions(event_id))

    # ------------------------------------------------------------------
    # Scan log
    # ------------------------------------------------------------------

    def get_scan_logs(self) -> list[ScanLogEntry]:
        return load_scan_logs(self.db)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    def get_history_count(self) -> int:
        return self.get_realized_summary()["count"]

    # ------------------------------------------------------------------
    # Internal: fetch + persist
    # ------------------------------------------------------------------

    def _persist_log(self, entry: ScanLogEntry) -> None:
        save_scan_log(entry, self.db)

    # ------------------------------------------------------------------
    # Step tracking (for TUI progress display)
    # ------------------------------------------------------------------

    def _step_start(self, name: str) -> None:
        self._steps.append(StepInfo(name=name, status="running", start_time=time.time()))
        self._emit_progress()

    def _step_done(self, detail: str = "") -> None:
        for s in reversed(self._steps):
            if s.status == "running":
                s.status = "done"
                s.detail = detail
                s.elapsed = time.time() - s.start_time
                break
        self._emit_progress()

    def _on_pipeline_progress(self, name: str, status: str, detail: str = "") -> None:
        """Callback for pipeline step progress."""
        if status == "start":
            self._step_start(name)
        elif status in ("done", "skip", "fail"):
            for s in reversed(self._steps):
                if s.status == "running":
                    s.status = status
                    s.detail = detail
                    s.elapsed = time.time() - s.start_time
                    break
            self._emit_progress()

    def _emit_progress(self) -> None:
        if self.on_progress:
            snapshot = [
                StepInfo(s.name, s.status, s.detail, s.start_time, s.elapsed)
                for s in self._steps
            ]
            self.on_progress(snapshot)

    def _steps_to_records(self) -> list[ScanStepRecord]:
        return [
            ScanStepRecord(name=s.name, status=s.status, detail=s.detail, elapsed=s.elapsed)
            for s in self._steps
            if s.status != "running"
        ]

    def _finish_log(self, status: str, error: str | None = None) -> None:
        if not self._current_log:
            return
        finish_log_entry(
            self._current_log,
            status,
            self._steps_to_records(),
            error=error,
        )
        self._persist_log(self._current_log)
        self._current_log = None
