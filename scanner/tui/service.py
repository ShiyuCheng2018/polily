"""ScanService: bridge between TUI and existing pipeline/paper_trading modules."""

import dataclasses
import logging
import time
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from scanner.api import PolymarketClient, parse_gamma_event
from scanner.core.config import ScannerConfig, load_config
from scanner.core.db import PolilyDB
from scanner.scan.pipeline import run_scan_pipeline
from scanner.scan.reporting import ScoredCandidate, TierResult
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
    """Provides data to TUI without coupling to Rich console or CLI."""

    def __init__(self, config: ScannerConfig | None = None):
        self.config = config or self._load_default_config()
        self.db = PolilyDB(self.config.archiving.db_file)
        self.tiers: TierResult | None = None
        self.total_scanned: int = 0
        self.on_progress: Callable[[list[StepInfo]], None] | None = None
        self.last_scan_id: str | None = None
        self._steps: list[StepInfo] = []
        self._current_log: ScanLogEntry | None = None
        self._load_from_archive()
        self._restore_narratives()

    def _load_default_config(self) -> ScannerConfig:
        minimal = Path("config.minimal.yaml")
        example = Path("config.example.yaml")
        if minimal.exists() and example.exists():
            return load_config(minimal, defaults_path=example)
        if example.exists():
            return load_config(example)
        return ScannerConfig()

    # --- Archive restore ---

    def _load_from_archive(self):
        """Load last scan results from archive on startup.

        TODO: v0.5.0 — rewrite to load from event_store / DB instead of JSON archives.
        """
        # Stubbed: scanner.archive was deleted. Will be rewritten in Task 1.10.
        pass

    # --- Scan log ---

    def get_scan_logs(self) -> list[ScanLogEntry]:
        return load_scan_logs(self.db)

    def _persist_log(self, entry: ScanLogEntry):
        save_scan_log(entry, self.db)

    # --- Step tracking ---

    def _step_start(self, name: str):
        self._steps.append(StepInfo(name=name, status="running", start_time=time.time()))
        self._emit_progress()

    def _step_done(self, detail: str = ""):
        for s in reversed(self._steps):
            if s.status == "running":
                s.status = "done"
                s.detail = detail
                s.elapsed = time.time() - s.start_time
                break
        self._emit_progress()

    def _on_pipeline_progress(self, name: str, status: str, detail: str = ""):
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

    def _emit_progress(self):
        if self.on_progress:
            snapshot = [
                StepInfo(s.name, s.status, s.detail, s.start_time, s.elapsed)
                for s in self._steps
            ]
            self.on_progress(snapshot)

    def _steps_to_records(self) -> list[ScanStepRecord]:
        return [
            ScanStepRecord(name=s.name, status=s.status, detail=s.detail, elapsed=s.elapsed)
            for s in self._steps if s.status != "running"
        ]

    # --- Scan ---

    async def fetch_and_scan(self) -> TierResult:
        """Run full pipeline: fetch -> filter -> score -> tier."""
        self._steps = []
        self._current_log = create_log_entry()
        self._persist_log(self._current_log)

        self._step_start("获取市场数据")
        markets = await self._fetch_markets()
        self._step_done(f"{len(markets)} 个")

        self.total_scanned = len(markets)
        if not markets:
            self.tiers = TierResult()
            self._finish_log("completed")
            return self.tiers

        import os
        os.environ["POLILY_TUI"] = "1"
        try:
            self.tiers = run_scan_pipeline(
                markets, self.config,
                progress_cb=self._on_pipeline_progress,
            )
        except Exception as e:
            self._finish_log("failed", error=str(e))
            raise
        finally:
            os.environ.pop("POLILY_TUI", None)

        # TODO: v0.5.0 — archive saving removed; will be rewritten against event_store
        if self.config.archiving.enabled and self._current_log:
            self.last_scan_id = self._current_log.scan_id

        # Restore previous AI narratives from analyses.json
        self._restore_narratives()

        self._finish_log("completed")
        return self.tiers

    def _restore_narratives(self):
        """Restore previous AI narratives from analyses DB to scan candidates.

        TODO: v0.5.0 Task 4.1 will rewrite this to use event_id-based analyses.
        For now, stubbed — fresh DB has no analyses to restore.
        """
        pass

    def _save_scan_narratives(self):
        """Save scan-generated narratives to analyses DB.

        TODO: v0.5.0 Task 4.1 will rewrite this to use event_id-based analyses.
        For now, stubbed — scan doesn't generate AI narratives (on-demand only).
        """
        pass

    def _finish_log(self, status: str, error: str | None = None):
        if not self._current_log:
            return
        research = len(self.tiers.tier_a) if self.tiers else 0
        watchlist = len(self.tiers.tier_b) if self.tiers else 0
        filtered = len(self.tiers.tier_c) if self.tiers else 0
        finish_log_entry(
            self._current_log, status, self._steps_to_records(),
            total_markets=self.total_scanned,
            research_count=research,
            watchlist_count=watchlist,
            filtered_count=filtered,
            error=error,
        )
        self._persist_log(self._current_log)
        self._current_log = None

    # --- Single market analysis ---

    def cancel_analysis(self):
        """Cancel the currently running AI analysis."""
        narrator = getattr(self, "_current_narrator", None)
        if narrator:
            narrator.cancel()
            logger.info("Analysis cancelled by user")

    async def analyze_market(self, market_id: str, *,
                             candidate: ScoredCandidate | None = None,
                             trigger_source: str = "manual",
                             on_heartbeat=None):
        """Run full AI analysis on a single market.

        Args:
            market_id: The market to analyze.
            candidate: If provided, use this candidate. Otherwise build one from API.
            trigger_source: 'manual' / 'scan' / 'scheduled'
            on_heartbeat: callback(elapsed, status) during AI call.
        """
        from datetime import datetime

        from scanner.agents.narrative_writer import NarrativeWriterAgent
        from scanner.analysis_store import (
            AnalysisVersion,
            append_analysis,
            get_event_analyses,
        )

        # Build candidate if not provided
        if candidate is None:
            candidate = await self._build_candidate(market_id)

        market = candidate.market
        # Use event_id if available, fall back to market_id for now
        event_id = getattr(market, "event_id", None) or market.market_id
        start_time = time.time()

        # Log entry
        log = create_log_entry()
        log.type = "analyze"
        log.event_id = event_id
        log.market_title = market.title
        self._steps = []
        self._current_log = log
        self._persist_log(log)

        try:
            # Step 1: Fetch real-time market data
            self._step_start("拉取实时数据")
            try:
                try:
                    prices = await self.fetch_current_prices([market.market_id])
                    new_price = prices.get(market.market_id)
                    if new_price is not None:
                        market.yes_price = new_price
                        market.no_price = round(1 - new_price, 4) if new_price else market.no_price
                except Exception as e:
                    logger.warning("Price fetch failed for %s: %s", market.market_id, e)

                try:
                    client = PolymarketClient(self.config.api)
                    try:
                        if market.clob_token_id_yes:
                            from scanner.orderbook import is_stale_book
                            bids, asks = await client.fetch_book(market.clob_token_id_yes)
                            if not is_stale_book(bids, asks):
                                market.book_depth_bids = bids
                                market.book_depth_asks = asks
                    finally:
                        await client.close()
                except Exception as e:
                    logger.warning("Orderbook fetch failed for %s: %s", market.market_id, e)

                from scanner.scan.scoring import compute_structure_score
                candidate.score = compute_structure_score(market, self.config.scoring.weights)

                from scanner.market_types.registry import find_matching_module
                enrichment_mod = find_matching_module(market)
                if enrichment_mod:
                    params = await enrichment_mod.fetch_price_params(market, self.config)
                    if params:
                        mp_result = enrichment_mod.detect_mispricing(market, params, self.config)
                        if mp_result:
                            candidate.mispricing = mp_result

                self._step_done(f"YES {market.yes_price:.2f}")
            except Exception as e:
                self._step_done(f"部分失败: {e}")

            # Step 2: AI decision analysis
            self._step_start("AI 决策分析")
            existing = get_event_analyses(event_id, self.db)
            narrator = NarrativeWriterAgent(self.config.ai.narrative_writer)
            self._current_narrator = narrator

            include_bias = self.config.execution_hints.show_conditional_advice
            narrative_output = await narrator.generate(
                candidate, include_bias=include_bias,
                on_heartbeat=on_heartbeat,
            )
            self._current_narrator = None
            self._step_done("完成")

            new_version_num = (existing[-1].version if existing else 0) + 1
            version = AnalysisVersion(
                version=new_version_num,
                created_at=datetime.now(UTC).isoformat(),
                prices_snapshot={market.market_id: {"yes": market.yes_price, "no": market.no_price}},
                mispricing_signal=candidate.mispricing.signal,
                mispricing_details=candidate.mispricing.details,
                narrative_output=narrative_output.model_dump(),
                trigger_source=trigger_source,
                structure_score=candidate.score.total if candidate.score else None,
                score_breakdown=dataclasses.asdict(candidate.score) if candidate.score else None,
                elapsed_seconds=time.time() - start_time,
            )

            append_analysis(event_id, version, self.db)
            candidate.narrative = narrative_output

            finish_log_entry(log, "completed", self._steps_to_records(), total_markets=1)
            self._persist_log(log)
            self._current_log = None
            return version

        except Exception as e:
            finish_log_entry(log, "failed", self._steps_to_records(), error=str(e))
            self._persist_log(log)
            self._current_log = None
            raise

    async def _build_candidate(self, market_id: str) -> ScoredCandidate:
        """Build a ScoredCandidate from market_id by fetching fresh data."""
        from scanner.scan.mispricing import detect_mispricing
        from scanner.scan.scoring import compute_structure_score

        # Fetch single market from Polymarket API
        client = PolymarketClient(self.config.api)
        try:
            market = await client.fetch_single_market(market_id)
            if market is None:
                raise ValueError(f"Market {market_id} not found on Polymarket")
        finally:
            await client.close()

        # Score + mispricing
        score = compute_structure_score(market, self.config.scoring.weights)
        mispricing = detect_mispricing(market, self.config.mispricing)
        return ScoredCandidate(market=market, score=score, mispricing=mispricing)

    def _sync_market_metadata(self, market):
        """Sync market metadata (type, token IDs) to state without changing status.

        TODO: v0.5.0 — rewrite to update markets table via event_store.
        """
        # Stubbed: market_states table was removed in v2 schema
        pass

    # --- Position analysis ---

    async def analyze_position(self, candidate: ScoredCandidate, entry_price: float,
                                side: str, days_held: float):
        """Run position analysis — delegates to analyze_market.

        NarrativeWriter agent reads paper_trades from DB and naturally
        adapts its analysis to include hold/reduce/exit advice.
        Returns PositionAdvice extracted from the NarrativeWriterOutput.
        """
        from scanner.agents.schemas import PositionAdvice

        version = await self.analyze_market(
            candidate.market.market_id,
            candidate=candidate,
            trigger_source="manual",
        )

        # Extract position advice from narrative output
        n = version.narrative_output if isinstance(version.narrative_output, dict) else {}
        action = n.get("action", "PASS")
        summary = n.get("summary", "")

        # Map NarrativeWriter action to position advice
        if action == "HOLD":
            advice = "hold"
        elif action == "REDUCE":
            advice = "reduce"
        elif action == "SELL":
            advice = "exit"
        elif action in ("BUY_YES", "BUY_NO"):
            logger.warning("Agent returned %s for market with open position — mapping to hold", action)
            advice = "hold"
        elif action == "WATCH":
            logger.warning("Agent returned WATCH for market with open position — mapping to reduce", action)
            advice = "reduce"
        else:
            logger.warning("Agent returned %s for market with open position — mapping to exit", action)
            advice = "exit"

        return PositionAdvice(
            advice=advice,
            reasoning=summary,
            thesis_intact=action in ("BUY_YES", "BUY_NO", "HOLD"),
            thesis_note=n.get("why_now") or n.get("why_not_now") or "",
            risk_note=n.get("risk_flags", [{}])[0].get("text", "") if n.get("risk_flags") else "",
            research_findings=[
                {"finding": f.get("finding", ""), "source": f.get("source", ""), "impact": f.get("impact", "")}
                for f in n.get("supporting_findings", [])[:3]
            ],
        )

    # --- Real-time price fetch ---

    async def fetch_current_prices(self, market_ids: list[str]) -> dict[str, float]:
        """Fetch current YES prices from Polymarket API for given market IDs."""
        client = PolymarketClient(self.config.api)
        http = await client._get_client()
        prices = {}
        try:
            for mid in market_ids:
                try:
                    resp = await http.get(
                        f"https://gamma-api.polymarket.com/markets/{mid}",
                        timeout=10,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        prices_raw = data.get("outcomePrices", "[]")
                        import json as _json
                        parsed = _json.loads(prices_raw) if isinstance(prices_raw, str) else prices_raw
                        if parsed:
                            prices[mid] = float(parsed[0])
                except Exception:
                    pass
        finally:
            await client.close()
        return prices

    async def _fetch_markets(self) -> list:
        client = PolymarketClient(self.config.api)
        try:
            events = await client.fetch_all_events(
                max_events=self.config.scanner.max_markets_to_fetch // 2,
            )
            markets = []
            for event in events:
                result = parse_gamma_event(event)
                # Handle both old (list[Market]) and new (tuple[EventRow, list[Market]]) return
                if isinstance(result, tuple):
                    _event_row, market_list = result
                    markets.extend(market_list)
                else:
                    markets.extend(result)
            return markets
        finally:
            await client.close()

    def get_all_market_states(self) -> dict:
        """Get all market states as {market_id: state_dict}.

        TODO: v0.5.0 — rewrite to use event_monitors + events tables.
        """
        # Stubbed: market_states table was removed in v2 schema
        return {}

    def get_monitor_count(self) -> int:
        """Get count of events with auto_monitor enabled."""
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM event_monitors WHERE auto_monitor = 1",
        ).fetchone()
        return row[0] if row else 0

    def get_unread_notification_count(self) -> int:
        """Get count of unread notifications."""
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM notifications WHERE is_read = 0",
        ).fetchone()
        return row[0] if row else 0

    def get_all_candidates(self) -> list[ScoredCandidate]:
        if not self.tiers:
            return []
        all_c = self.tiers.tier_a + self.tiers.tier_b + self.tiers.tier_c
        return sorted(all_c, key=lambda c: c.score.total, reverse=True)

    def get_research(self) -> list[ScoredCandidate]:
        return self.tiers.tier_a if self.tiers else []

    def get_watchlist(self) -> list[ScoredCandidate]:
        return self.tiers.tier_b if self.tiers else []

    def mark_paper_trade(self, market_id: str, title: str, side: str,
                         price: float, market_type: str | None = None,
                         score: float | None = None) -> str:
        """Mark a paper trade.

        TODO: v0.5.0 — rewrite to use paper_store.
        """
        raise NotImplementedError("v0.5.0 TODO: paper trades via paper_store")

    def get_paper_trades(self) -> list:
        """TODO: v0.5.0 — rewrite to use paper_store."""
        return []

    def get_resolved_trades(self) -> list:
        """TODO: v0.5.0 — rewrite to use paper_store."""
        return []

    def get_history_count(self) -> int:
        return len(self.get_resolved_trades())

    def get_resolved_stats(self) -> dict:
        return {
            "total": 0, "wins": 0,
            "win_rate": 0,
            "total_pnl": 0,
            "total_friction_pnl": 0,
        }

    def get_paper_stats(self) -> dict:
        """TODO: v0.5.0 — rewrite to use paper_store."""
        return {
            "total_trades": 0, "open": 0, "resolved": 0,
            "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_paper_pnl": 0.0, "total_friction_adjusted_pnl": 0.0,
        }
