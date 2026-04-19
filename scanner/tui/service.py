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
from scanner.core.event_store import (
    EventRow,
    get_event,
    get_event_markets,
)
from scanner.core.monitor_store import get_event_monitor, update_next_check_at
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


class ActivePositionsError(Exception):
    """Raised when an operation would orphan open positions (e.g. disabling
    monitor on an event the user still holds shares in)."""


class ScanService:
    """DB-first bridge between TUI views, scan pipeline, AI agent, and DB."""

    def __init__(
        self,
        config: ScannerConfig | None = None,
        db: PolilyDB | None = None,
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
    ) -> AnalysisVersion:
        """Run AI analysis on an event. Agent reads DB autonomously."""
        event = get_event(event_id, self.db)
        if event is None:
            raise ValueError(f"Event {event_id} not found in DB")
        markets = get_event_markets(event_id, self.db)

        start_time = time.time()

        # Check if user has open positions in this event
        has_position, position_summary = self._compute_position_context(event_id)

        # Get existing analyses for version numbering
        existing = get_event_analyses(event_id, self.db)
        new_version_num = (existing[-1].version if existing else 0) + 1

        # Run NarrativeWriter — agent reads DB and searches web autonomously
        narrator = NarrativeWriterAgent(self.config.ai.narrative_writer)
        self._current_narrator = narrator
        try:
            narrative_output = await narrator.generate(
                event_id=event_id,
                has_position=has_position,
                position_summary=position_summary,
                on_heartbeat=on_heartbeat,
            )
        finally:
            self._current_narrator = None

        # Build price snapshot
        prices_snapshot = {}
        for mr in markets:
            prices_snapshot[mr.market_id] = {
                "yes": mr.yes_price,
                "no": mr.no_price,
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

        append_analysis(event_id, version, self.db)

        # Update next_check_at if AI provided one
        if narrative_output.next_check_at:
            update_next_check_at(
                event_id,
                narrative_output.next_check_at,
                narrative_output.next_check_reason,
                self.db,
            )
            # notify_daemon is called inside update_next_check_at

        return version

    def cancel_analysis(self) -> None:
        """Cancel the currently running AI analysis."""
        narrator = self._current_narrator
        if narrator:
            narrator.cancel()
            logger.info("Analysis cancelled by user")

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
                   em.next_check_at AS next_check_at,
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
        MarketDetailView to show "无持仓" for live positions.
        """
        event = get_event(event_id, self.db)
        if event is None:
            return None
        markets = get_event_markets(event_id, self.db)
        analyses = get_event_analyses(event_id, self.db)
        _positions = self.positions.get_event_positions(event_id)
        trades = [
            {
                "market_id": p["market_id"],
                "side": p["side"],
                "title": p.get("title") or "",
                "entry_price": p["avg_cost"],
                "position_size_usd": p["cost_basis"],
            }
            for p in _positions
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
        """
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

    def execute_buy(self, *, market_id: str, side: str, shares: float) -> dict:
        return self.trade_engine.execute_buy(
            market_id=market_id, side=side, shares=shares,
        )

    def execute_sell(self, *, market_id: str, side: str, shares: float) -> dict:
        return self.trade_engine.execute_sell(
            market_id=market_id, side=side, shares=shares,
        )

    def topup(self, amount: float) -> None:
        self.wallet.topup(amount)

    def withdraw(self, amount: float) -> None:
        self.wallet.withdraw(amount)

    def get_wallet_snapshot(self) -> dict:
        return self.wallet.get_snapshot()

    def get_wallet_transactions(self, limit: int = 100) -> list[dict]:
        return self.wallet.list_transactions(limit=limit)

    def get_all_positions(self) -> list[dict]:
        return self.positions.get_all_positions()

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
        """
        if not enable and self.get_event_position_count(event_id) > 0:
            raise ActivePositionsError(
                f"Cannot disable monitoring — event {event_id} has open positions",
            )
        toggle_auto_monitor(event_id, enable=enable, db=self.db)

    def get_event_position_count(self, event_id: str) -> int:
        """Count open positions across every market in the event."""
        return len(self.positions.get_event_positions(event_id))

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def get_unread_notification_count(self) -> int:
        """Count unread notifications."""
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE is_read = 0",
        ).fetchone()
        return row[0] if row else 0

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
