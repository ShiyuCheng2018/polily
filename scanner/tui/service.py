"""ScanService: bridge between TUI and existing pipeline/paper_trading modules."""

import contextlib
import dataclasses
import logging
import time
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from scanner.api import PolymarketClient, parse_gamma_event
from scanner.archive import save_scan_unified
from scanner.config import ScannerConfig, load_config
from scanner.db import PolilyDB
from scanner.paper_trading import PaperTradingDB
from scanner.pipeline import run_scan_pipeline
from scanner.reporting import ScoredCandidate, TierResult
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
        """Load last scan results from archive on startup."""
        from datetime import datetime

        from scanner.archive import get_latest_scan_id, load_latest_archive
        from scanner.mispricing import MispricingResult
        from scanner.models import Market
        from scanner.scoring import ScoreBreakdown

        data = load_latest_archive(self.config.archiving.archive_dir)
        if not data:
            return

        self.last_scan_id = get_latest_scan_id(self.config.archiving.archive_dir)
        tier_a, tier_b, tier_c = [], [], []
        now = datetime.now(UTC)

        for entry in data:
            try:
                # Parse resolution_time if available
                res_time = None
                if entry.get("resolution_time"):
                    with contextlib.suppress(ValueError, TypeError):
                        res_time = datetime.fromisoformat(entry["resolution_time"])

                market = Market(
                    market_id=entry.get("market_id", ""),
                    title=entry.get("title", ""),
                    description=entry.get("description"),
                    rules=entry.get("rules"),
                    outcomes=["Yes", "No"],
                    yes_price=entry.get("yes_price"),
                    no_price=entry.get("no_price"),
                    best_bid_yes=entry.get("best_bid_yes"),
                    best_ask_yes=entry.get("best_ask_yes"),
                    spread_yes=entry.get("spread_yes"),
                    volume=entry.get("volume"),
                    open_interest=entry.get("open_interest"),
                    market_type=entry.get("market_type"),
                    category=entry.get("category"),
                    tags=entry.get("tags", []),
                    resolution_source=entry.get("resolution_source"),
                    resolution_time=res_time,
                    data_fetched_at=now,
                    event_slug=entry.get("event_slug"),
                    market_slug=entry.get("market_slug"),
                    clob_token_id_yes=entry.get("clob_token_id_yes"),
                    condition_id=entry.get("condition_id"),
                )
                bd = entry.get("structure_score_breakdown", {})
                score = ScoreBreakdown(
                    liquidity_structure=bd.get("liquidity_structure", 0),
                    objective_verifiability=bd.get("objective_verifiability", 0),
                    probability_space=bd.get("probability_space", 0),
                    time_structure=bd.get("time_structure", 0),
                    trading_friction=bd.get("trading_friction", 0),
                    total=entry.get("structure_score", 0),
                )
                mispricing = MispricingResult(
                    signal=entry.get("mispricing_signal", "none"),
                    direction=entry.get("mispricing_direction"),
                    theoretical_fair_value=entry.get("theoretical_fair_value"),
                    deviation_pct=entry.get("mispricing_deviation_pct"),
                    details=entry.get("mispricing_details"),
                )
                # Restore narrative if available
                narrative = None
                n_data = entry.get("narrative")
                if n_data and isinstance(n_data, dict):
                    from scanner.agents.schemas import NarrativeWriterOutput
                    try:
                        # Ensure market_id is present
                        n_data.setdefault("market_id", entry.get("market_id", ""))
                        # Pre-process old risk_flags format (list[str] → list[dict])
                        if n_data.get("risk_flags") and isinstance(n_data["risk_flags"][0], str):
                            n_data["risk_flags"] = [
                                {"text": rf, "severity": "warning"} for rf in n_data["risk_flags"]
                            ]
                        narrative = NarrativeWriterOutput.model_validate(n_data)
                    except Exception:
                        pass

                candidate = ScoredCandidate(market=market, score=score, mispricing=mispricing, narrative=narrative)

                tier = entry.get("tier", "filtered")
                if tier == "research":
                    tier_a.append(candidate)
                elif tier == "watchlist":
                    tier_b.append(candidate)
                else:
                    tier_c.append(candidate)
            except Exception as e:
                logger.debug("Skip archive entry: %s", e)
                continue

        self.tiers = TierResult(tier_a=tier_a, tier_b=tier_b, tier_c=tier_c)
        self.total_scanned = len(data)

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

        # Save unified archive (use scan log's start-time ID for consistency)
        if self.config.archiving.enabled:
            self.last_scan_id = save_scan_unified(
                self.tiers, self.config.archiving.archive_dir,
                scan_id=self._current_log.scan_id if self._current_log else None,
            )

        # Restore previous AI narratives from analyses.json
        self._restore_narratives()

        self._finish_log("completed")
        return self.tiers

    def _restore_narratives(self):
        """Restore previous AI narratives from analyses DB to scan candidates."""
        from scanner.agents.schemas import NarrativeWriterOutput
        from scanner.analysis_store import get_market_analyses

        if not self.tiers:
            return

        for c in self.tiers.tier_a + self.tiers.tier_b + self.tiers.tier_c:
            versions = get_market_analyses(c.market.market_id, self.db)
            if not versions:
                continue
            latest = versions[-1]
            n_data = latest.narrative_output
            if not n_data or not isinstance(n_data, dict):
                continue
            try:
                n_data.setdefault("market_id", c.market.market_id)
                if n_data.get("risk_flags") and isinstance(n_data["risk_flags"][0], str):
                    n_data["risk_flags"] = [
                        {"text": rf, "severity": "warning"} for rf in n_data["risk_flags"]
                    ]
                c.narrative = NarrativeWriterOutput.model_validate(n_data)
            except Exception:
                pass

    def _save_scan_narratives(self):
        """Save scan-generated narratives to analyses DB as incremental versions."""
        from datetime import datetime

        from scanner.analysis_store import (
            AnalysisVersion,
            append_analysis,
            get_market_analyses,
        )
        if not self.tiers:
            return
        now_iso = datetime.now(UTC).isoformat()

        for c in self.tiers.tier_a + self.tiers.tier_b:
            if not c.narrative:
                continue
            mid = c.market.market_id
            existing = get_market_analyses(mid, self.db)
            last_version = existing[-1].version if existing else 0
            version = AnalysisVersion(
                version=last_version + 1,
                created_at=now_iso,
                market_title=c.market.title,
                yes_price_at_analysis=c.market.yes_price,
                analyst_output={},
                narrative_output=c.narrative.model_dump(),
                trigger_source="scan",
                elapsed_seconds=0,
            )
            append_analysis(mid, version, self.db)

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
            get_market_analyses,
        )

        # Build candidate if not provided
        if candidate is None:
            candidate = await self._build_candidate(market_id)

        market = candidate.market
        start_time = time.time()

        # Log entry — persist immediately so it shows as "running"
        log = create_log_entry()
        log.type = "analyze"
        log.market_id = market.market_id
        log.market_title = market.title
        self._steps = []
        self._current_log = log
        self._persist_log(log)

        price_change = ""

        try:
            # Step 1: Fetch real-time market data (price + orderbook)
            self._step_start("拉取实时数据")
            _ = {  # scan snapshot for debugging
                "yes_price": market.yes_price,
                "no_price": market.no_price,
                "spread_pct_yes": market.spread_pct_yes,
                "total_bid_depth_usd": market.total_bid_depth_usd,
                "total_ask_depth_usd": market.total_ask_depth_usd,
                "data_time": market.data_fetched_at.isoformat() if market.data_fetched_at else "?",
            }
            try:
                # Fetch latest price from Polymarket API
                try:
                    prices = await self.fetch_current_prices([market.market_id])
                    new_price = prices.get(market.market_id)
                    if new_price is not None:
                        old_price = market.yes_price
                        market.yes_price = new_price
                        market.no_price = round(1 - new_price, 4) if new_price else market.no_price
                        market.data_fetched_at = datetime.now(UTC)
                except Exception as e:
                    logger.warning("Price fetch failed for %s: %s", market.market_id, e)

                # Fetch latest orderbook (independent of price fetch)
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

                # Recalculate score with fresh data
                from scanner.scoring import compute_structure_score
                candidate.score = compute_structure_score(
                    market, self.config.scoring.weights,
                )

                # Recalculate mispricing if crypto
                from scanner.market_types.registry import find_matching_module
                enrichment_mod = find_matching_module(market)
                if enrichment_mod:
                    params = await enrichment_mod.fetch_price_params(market, self.config)
                    if params:
                        mp_result = enrichment_mod.detect_mispricing(market, params, self.config)
                        if mp_result:
                            candidate.mispricing = mp_result

                # Build change context
                price_change = ""
                if new_price is not None and old_price is not None and old_price > 0:
                    change_pct = (new_price - old_price) / old_price * 100
                    price_change = f"YES 价格: 扫描时 {old_price:.2f} → 现在 {new_price:.2f} ({change_pct:+.1f}%)"

                detail = f"YES {market.yes_price:.2f}"
                if price_change:
                    detail += f" | {price_change}"
                self._step_done(detail)
            except Exception as e:
                self._step_done(f"部分失败: {e}")

            # Step 2: AI decision analysis — agent reads DB + searches web on its own
            self._step_start("AI 决策分析")
            existing = get_market_analyses(market.market_id, self.db)
            narrator = NarrativeWriterAgent(self.config.ai.narrative_writer)
            self._current_narrator = narrator

            include_bias = self.config.execution_hints.show_conditional_advice
            from scanner.movement_store import get_movement_summary
            movement_context = get_movement_summary(market.market_id, self.db)
            narrative_output = await narrator.generate(
                candidate, include_bias=include_bias,
                on_heartbeat=on_heartbeat,
                extra_context=movement_context,
            )
            self._current_narrator = None
            self._step_done("完成")

            # Build version with score snapshot
            new_version_num = (existing[-1].version if existing else 0) + 1

            version = AnalysisVersion(
                version=new_version_num,
                created_at=datetime.now(UTC).isoformat(),
                market_title=market.title,
                yes_price_at_analysis=market.yes_price,
                analyst_output={},
                mispricing_signal=candidate.mispricing.signal,
                mispricing_details=candidate.mispricing.details,
                narrative_output=narrative_output.model_dump(),
                trigger_source=trigger_source,
                structure_score=candidate.score.total if candidate.score else None,
                score_breakdown=dataclasses.asdict(candidate.score) if candidate.score else None,
                elapsed_seconds=time.time() - start_time,
            )

            # Persist analysis
            append_analysis(market.market_id, version, self.db)
            candidate.narrative = narrative_output

            # Sync market metadata (market_type, condition_id, etc.) to state
            # but do NOT transition status — that's the user's decision.
            self._sync_market_metadata(market)

            # Persist next_check_at to market_states if market already tracked
            if narrative_output.next_check_at:
                from scanner.market_state import get_market_state, set_market_state
                state = get_market_state(market.market_id, self.db)
                if state:
                    state.next_check_at = narrative_output.next_check_at
                    set_market_state(market.market_id, state, self.db)
                    from scanner.daemon_notify import notify_daemon
                    notify_daemon()

            # Log
            finish_log_entry(
                log, "completed", self._steps_to_records(),
                total_markets=1,
            )
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
        from scanner.mispricing import detect_mispricing
        from scanner.scoring import compute_structure_score

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
        """Sync market metadata (type, token IDs) to state without changing status."""
        from scanner.market_state import get_market_state, set_market_state

        mid = market.market_id
        state = get_market_state(mid, self.db)
        if state is None:
            return

        state.resolution_time = market.resolution_time.isoformat() if market.resolution_time else None
        state.market_type = getattr(market, "market_type", None)
        state.clob_token_id_yes = getattr(market, "clob_token_id_yes", None)
        state.condition_id = getattr(market, "condition_id", None)
        set_market_state(mid, state, self.db)

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
        if action in ("BUY_YES", "BUY_NO"):
            advice = "hold"
        elif action == "WATCH":
            advice = "reduce"
        else:
            advice = "exit"

        return PositionAdvice(
            advice=advice,
            reasoning=summary,
            thesis_intact=action in ("BUY_YES", "BUY_NO", "WATCH"),
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
                markets.extend(parse_gamma_event(event))
            return markets
        finally:
            await client.close()

    def get_all_market_states(self) -> dict:
        """Get all market states as {market_id: MarketState}."""
        rows = self.db.conn.execute("SELECT * FROM market_states").fetchall()
        from scanner.market_state import _row_to_state
        return {r["market_id"]: _row_to_state(r) for r in rows}

    def get_monitor_count(self) -> int:
        """Get count of markets with auto_monitor enabled."""
        row = self.db.conn.execute(
            "SELECT COUNT(*) FROM market_states WHERE auto_monitor = 1",
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

    def _paper_db(self) -> PaperTradingDB:
        return PaperTradingDB(
            self.db,
            position_size_usd=self.config.paper_trading.default_position_size_usd,
            friction_pct=self.config.paper_trading.assumed_round_trip_friction_pct,
        )

    def mark_paper_trade(self, market_id: str, title: str, side: str,
                         price: float, market_type: str | None = None,
                         score: float | None = None) -> str:
        ptdb = self._paper_db()
        trade = ptdb.mark(
            market_id=market_id, title=title, side=side,
            entry_price=price, market_type=market_type,
            structure_score=score,
            scan_id=getattr(self, "last_scan_id", None),
        )
        return trade.id

    def get_paper_trades(self) -> list:
        return self._paper_db().list_open()

    def get_paper_stats(self) -> dict:
        return self._paper_db().stats()
