"""ScanService v0.5.0: DB-first, event-level bridge between TUI and backend."""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from scanner.agents.narrative_writer import NarrativeWriterAgent
from scanner.analysis_store import AnalysisVersion, append_analysis, get_event_analyses
from scanner.api import PolymarketClient, parse_gamma_event
from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    EventRow,
    MarketRow,
    get_event,
    get_event_markets,
    upsert_event,
    upsert_market,
)
from scanner.core.monitor_store import get_event_monitor, update_next_check_at
from scanner.core.paper_store import create_paper_trade as _create_paper_trade
from scanner.core.paper_store import get_open_trades as _get_open_trades
from scanner.core.paper_store import get_resolved_trades as _get_resolved_trades
from scanner.core.paper_store import get_trade_stats as _get_trade_stats
from scanner.daemon.auto_monitor import toggle_auto_monitor
from scanner.monitor.store import get_event_movements
from scanner.scan.pipeline import run_scan_pipeline
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


class ScanService:
    """DB-first bridge between TUI views, scan pipeline, AI agent, and DB."""

    def __init__(
        self,
        config: ScannerConfig | None = None,
        db: PolilyDB | None = None,
    ):
        self.config = config or self._load_default_config()
        self.db = db or PolilyDB(self.config.archiving.db_file)

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
    # Scan
    # ------------------------------------------------------------------

    async def fetch_and_scan(self) -> None:
        """Run full pipeline: fetch events -> persist to DB -> score -> tier."""
        self._steps = []
        self._current_log = create_log_entry()
        self._persist_log(self._current_log)

        self._step_start("获取市场数据")
        event_rows, markets = await self._fetch_events()
        self._step_done(f"{len(markets)} 个")

        self.total_scanned = len(markets)
        if not markets:
            self._finish_log("completed")
            return

        # Persist events + markets to DB before pipeline
        self._step_start("持久化到数据库")
        self._persist_scan_data(event_rows, markets)
        self._step_done(f"{len(event_rows)} 事件")

        os.environ["POLILY_TUI"] = "1"
        try:
            run_scan_pipeline(
                markets,
                self.config,
                db=self.db,
                progress_cb=self._on_pipeline_progress,
            )
        except Exception as e:
            self._finish_log("failed", error=str(e))
            raise
        finally:
            os.environ.pop("POLILY_TUI", None)

        if self.config.archiving.enabled and self._current_log:
            self.last_scan_id = self._current_log.scan_id

        self._finish_log("completed")

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    async def analyze_event(
        self,
        event_id: str,
        trigger_source: str = "manual",
        on_heartbeat=None,
    ) -> AnalysisVersion:
        """Run AI analysis on an event. Reads all data from DB."""
        from scanner.scan.mispricing import MispricingResult
        from scanner.scan.reporting import ScoredCandidate
        from scanner.scan.scoring import ScoreBreakdown

        event = get_event(event_id, self.db)
        if event is None:
            raise ValueError(f"Event {event_id} not found in DB")
        markets = get_event_markets(event_id, self.db)

        start_time = time.time()

        # Build a ScoredCandidate from DB data (use first market as representative)
        market_row = markets[0] if markets else None
        # Build a minimal Market-like object for the agent
        from scanner.core.models import Market
        m = Market(
            market_id=market_row.market_id if market_row else event_id,
            title=event.title,
            description=event.description,
            event_id=event_id,
            yes_price=market_row.yes_price if market_row else None,
            no_price=market_row.no_price if market_row else None,
            outcomes=["Yes", "No"],
            data_fetched_at=datetime.now(UTC),
        )

        total = event.structure_score or 0
        score = ScoreBreakdown(
            liquidity_structure=0, objective_verifiability=0,
            probability_space=0, time_structure=0, trading_friction=0,
            total=total,
        )
        mispricing = MispricingResult(signal="none")
        candidate = ScoredCandidate(market=m, score=score, mispricing=mispricing)

        # Get existing analyses for version numbering
        existing = get_event_analyses(event_id, self.db)
        new_version_num = (existing[-1].version if existing else 0) + 1

        # Run NarrativeWriter
        narrator = NarrativeWriterAgent(self.config.ai.narrative_writer)
        self._current_narrator = narrator
        try:
            include_bias = self.config.execution_hints.show_conditional_advice
            narrative_output = await narrator.generate(
                candidate,
                include_bias=include_bias,
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
            # Notify daemon to register check_job
            try:
                from scanner.daemon.notify import notify_daemon
                notify_daemon()
            except Exception:
                pass

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

    def get_research_events(self) -> list[dict]:
        """Return events with tier in (research, watchlist), sorted by score desc."""
        return self._query_events(
            "WHERE e.tier IN ('research', 'watchlist') AND e.closed = 0"
        )

    def get_all_events(self) -> list[dict]:
        """Return all non-closed events, sorted by score desc."""
        return self._query_events("WHERE e.closed = 0")

    def _query_events(self, where_clause: str) -> list[dict]:
        """Query events with summary fields (market_count, monitor, position)."""
        sql = f"""
            SELECT e.*,
                   COUNT(DISTINCT mk.market_id) AS market_count,
                   COALESCE(em.auto_monitor, 0) AS is_monitored,
                   COUNT(DISTINCT pt.id) AS position_count
            FROM events e
            LEFT JOIN markets mk ON mk.event_id = e.event_id
            LEFT JOIN event_monitors em ON em.event_id = e.event_id
            LEFT JOIN paper_trades pt ON pt.event_id = e.event_id AND pt.status = 'open'
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
            results.append({
                "event": event,
                "market_count": d["market_count"],
                "is_monitored": bool(d["is_monitored"]),
                "has_position": d["position_count"] > 0,
            })
        return results

    def get_event_detail(self, event_id: str) -> dict | None:
        """Return full detail for an event: event, markets, analyses, trades, monitor, movements."""
        event = get_event(event_id, self.db)
        if event is None:
            return None
        markets = get_event_markets(event_id, self.db)
        analyses = get_event_analyses(event_id, self.db)
        from scanner.core.paper_store import get_event_open_trades
        trades = get_event_open_trades(event_id, self.db)
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

    # ------------------------------------------------------------------
    # Paper trades
    # ------------------------------------------------------------------

    def create_paper_trade(
        self,
        *,
        event_id: str,
        market_id: str,
        title: str,
        side: str,
        entry_price: float,
        position_size_usd: float,
    ) -> str:
        """Create a paper trade. Returns trade ID."""
        return _create_paper_trade(
            event_id=event_id,
            market_id=market_id,
            title=title,
            side=side,
            entry_price=entry_price,
            position_size_usd=position_size_usd,
            db=self.db,
        )

    def get_open_trades(self) -> list[dict]:
        return _get_open_trades(self.db)

    def get_resolved_trades(self) -> list[dict]:
        return _get_resolved_trades(self.db)

    def get_trade_stats(self) -> dict:
        return _get_trade_stats(self.db)

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
        """Enable or disable monitoring for an event."""
        toggle_auto_monitor(event_id, enable=enable, db=self.db)

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
        return len(self.get_resolved_trades())

    # ------------------------------------------------------------------
    # Internal: fetch + persist
    # ------------------------------------------------------------------

    async def _fetch_events(self) -> tuple[list[EventRow], list]:
        """Fetch events from Gamma API, returning (EventRow list, Market list)."""
        client = PolymarketClient(self.config.api)
        try:
            events_data = await client.fetch_all_events(
                max_events=self.config.scanner.max_markets_to_fetch // 2,
            )
            all_event_rows: list[EventRow] = []
            all_markets = []
            for event_data in events_data:
                event_row, market_list = parse_gamma_event(event_data)
                all_event_rows.append(event_row)
                all_markets.extend(market_list)
            return all_event_rows, all_markets
        finally:
            await client.close()

    def _persist_scan_data(self, event_rows: list[EventRow], markets: list) -> None:
        """Upsert events + markets to DB before pipeline runs."""
        from scanner.core.models import Market as MarketModel

        for er in event_rows:
            upsert_event(er, self.db)

        for m in markets:
            if not isinstance(m, MarketModel):
                continue
            mr = MarketRow(
                market_id=m.market_id,
                event_id=m.event_id or "",
                question=m.title,
                slug=getattr(m, "market_slug", None),
                description=m.description,
                group_item_title=m.group_item_title,
                group_item_threshold=m.group_item_threshold,
                condition_id=m.condition_id,
                question_id=m.question_id,
                clob_token_id_yes=m.clob_token_id_yes,
                clob_token_id_no=m.clob_token_id_no,
                neg_risk=m.neg_risk,
                neg_risk_request_id=m.neg_risk_request_id,
                neg_risk_other=m.neg_risk_other,
                resolution_source=m.resolution_source,
                end_date=m.resolution_time.isoformat() if m.resolution_time else None,
                volume=m.volume,
                liquidity=getattr(m, "liquidity", None),
                yes_price=m.yes_price,
                no_price=m.no_price,
                best_bid=m.best_bid_yes,
                best_ask=m.best_ask_yes,
                spread=m.spread_yes,
                accepting_orders=1 if m.accepting_orders else 0,
                updated_at=datetime.now(UTC).isoformat(),
            )
            upsert_market(mr, self.db)

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
        # Count from DB after pipeline updated tiers
        research = self.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE tier = 'research' AND closed = 0",
        ).fetchone()[0]
        watchlist = self.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE tier = 'watchlist' AND closed = 0",
        ).fetchone()[0]
        filtered = self.db.conn.execute(
            "SELECT COUNT(*) FROM events WHERE tier = 'filtered' AND closed = 0",
        ).fetchone()[0]
        finish_log_entry(
            self._current_log,
            status,
            self._steps_to_records(),
            total_markets=self.total_scanned,
            research_count=research,
            watchlist_count=watchlist,
            filtered_count=filtered,
            error=error,
        )
        self._persist_log(self._current_log)
        self._current_log = None
