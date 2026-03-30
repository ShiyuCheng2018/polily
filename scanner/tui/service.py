"""ScanService: bridge between TUI and existing pipeline/paper_trading modules."""

import contextlib
import logging
import time
from datetime import UTC
from pathlib import Path
from typing import TYPE_CHECKING

from scanner.api import PolymarketClient, parse_gamma_event
from scanner.archive import save_scan_unified
from scanner.config import ScannerConfig, load_config
from scanner.paper_trading import PaperTradingDB
from scanner.pipeline import run_scan_pipeline
from scanner.reporting import ScoredCandidate, TierResult
from scanner.scan_log import (
    ScanLogEntry,
    ScanStepRecord,
    create_log_entry,
    finish_log_entry,
    load_scan_logs,
    save_scan_logs,
)
from scanner.tui.views.scan_log import StepInfo

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


class ScanService:
    """Provides data to TUI without coupling to Rich console or CLI."""

    def __init__(self, config: ScannerConfig | None = None):
        self.config = config or self._load_default_config()
        self.tiers: TierResult | None = None
        self.total_scanned: int = 0
        self.on_progress: Callable[[list[StepInfo]], None] | None = None
        self.last_scan_id: str | None = None
        self._steps: list[StepInfo] = []
        self._current_log: ScanLogEntry | None = None
        self._load_from_archive()

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
                    resolution_source=entry.get("resolution_source"),
                    resolution_time=res_time,
                    data_fetched_at=now,
                    event_slug=entry.get("event_slug"),
                    market_slug=entry.get("market_slug"),
                )
                bd = entry.get("structure_score_breakdown", {})
                score = ScoreBreakdown(
                    time_to_resolution=bd.get("time_to_resolution", 0),
                    objectivity=bd.get("objectivity", 0),
                    probability_zone=bd.get("probability_zone", 0),
                    liquidity_depth=bd.get("liquidity_depth", 0),
                    exitability=bd.get("exitability", 0),
                    catalyst_proxy=bd.get("catalyst_proxy", 0),
                    small_account_friendliness=bd.get("small_account_friendliness", 0),
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
                    with contextlib.suppress(Exception):
                        narrative = NarrativeWriterOutput(
                            market_id=entry.get("market_id", ""),
                            summary=n_data.get("summary", ""),
                            why_it_passed=n_data.get("why_it_passed", []),
                            risk_flags=n_data.get("risk_flags", []),
                            counterparty_note=n_data.get("counterparty_note", ""),
                            research_checklist=n_data.get("research_checklist", []),
                            suggested_style=n_data.get("suggested_style", "watch_only"),
                            one_line_verdict=n_data.get("one_line_verdict", ""),
                        )

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
        return load_scan_logs(self.config.archiving.scan_log_file)

    def _persist_log(self, entry: ScanLogEntry):
        logs = self.get_scan_logs()
        # Replace running entry or append new
        logs = [existing for existing in logs if existing.scan_id != entry.scan_id]
        logs.append(entry)
        save_scan_logs(logs, self.config.archiving.scan_log_file,
                       self.config.archiving.scan_log_max_entries)

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

        # Save scan narratives as v1 in analyses store
        self._save_scan_narratives()

        self._finish_log("completed")
        return self.tiers

    def _save_scan_narratives(self):
        """Save scan-generated narratives to analyses store as incremental versions.
        Single file read/write for all candidates."""
        from datetime import datetime

        from scanner.analysis_store import (
            AnalysisVersion,
            load_analyses,
            save_analyses,
        )
        if not self.tiers:
            return
        analyses_path = self.config.archiving.analyses_file
        now_iso = datetime.now(UTC).isoformat()
        all_data = load_analyses(analyses_path)

        for c in self.tiers.tier_a + self.tiers.tier_b:
            if not c.narrative:
                continue
            mid = c.market.market_id
            raw_list = all_data.get(mid, [])
            last_version = raw_list[-1].get("version", 0) if raw_list else 0
            version = AnalysisVersion(
                version=last_version + 1,
                created_at=now_iso,
                market_title=c.market.title,
                yes_price_at_analysis=c.market.yes_price,
                analyst_output={},
                narrative_output=c.narrative.model_dump(),
                elapsed_seconds=0,
                previous_version=last_version if last_version else None,
            )
            if mid not in all_data:
                all_data[mid] = []
            all_data[mid].append(version.model_dump())
            all_data[mid] = all_data[mid][-10:]  # max 10 versions

        save_analyses(all_data, analyses_path)

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

    async def analyze_market(self, candidate: ScoredCandidate):
        """Run full AI analysis on a single market."""
        from datetime import datetime

        from scanner.agents.market_analyst import MarketAnalystAgent
        from scanner.agents.narrative_writer import NarrativeWriterAgent
        from scanner.analysis_store import (
            AnalysisVersion,
            append_analysis,
            build_previous_context,
            get_market_analyses,
        )

        market = candidate.market
        analyses_path = self.config.archiving.analyses_file
        start_time = time.time()

        # Log entry — persist immediately so it shows as "running"
        log = create_log_entry()
        log.type = "analyze"
        log.market_id = market.market_id
        log.market_title = market.title
        self._steps = []
        self._current_log = log
        self._persist_log(log)

        try:
            # Step 1: MarketAnalyst
            self._step_start("AI 语义分析")
            analyst = MarketAnalystAgent(self.config.ai.market_analyst, self.config.heuristics)
            analyst_output = await analyst.analyze(market)
            self._step_done("完成")

            # Step 2: Mispricing (crypto only)
            mispricing_signal = candidate.mispricing.signal
            mispricing_details = candidate.mispricing.details
            if market.market_type == "crypto_threshold":
                self._step_start("加密货币定价检测")
                try:
                    from scanner.mispricing import detect_mispricing
                    from scanner.price_feeds import BinancePriceFeed
                    feed = BinancePriceFeed()
                    try:
                        params = await feed.get_crypto_params(
                            market.title,
                            vol_days=self.config.mispricing.crypto.volatility_lookback_days,
                        )
                    finally:
                        await feed.close()
                    if params:
                        mp = detect_mispricing(market, self.config.mispricing, **params)
                        mispricing_signal = mp.signal
                        mispricing_details = mp.details
                        candidate.mispricing = mp
                    self._step_done("完成")
                except Exception as e:
                    self._step_done(f"跳过: {e}")

            # Step 3: NarrativeWriter with previous context
            self._step_start("AI 撰写分析")
            existing = get_market_analyses(market.market_id, analyses_path)
            narrator = NarrativeWriterAgent(self.config.ai.narrative_writer)
            context = build_previous_context(existing)
            narrative_output = await narrator.generate(candidate, context=context)
            self._step_done("完成")

            # Build version
            prev_version = existing[-1].version if existing else None
            new_version_num = (prev_version or 0) + 1

            version = AnalysisVersion(
                version=new_version_num,
                created_at=datetime.now(UTC).isoformat(),
                market_title=market.title,
                yes_price_at_analysis=market.yes_price,
                analyst_output=analyst_output.model_dump(),
                mispricing_signal=mispricing_signal,
                mispricing_details=mispricing_details,
                narrative_output=narrative_output.model_dump(),
                previous_version=prev_version,
                elapsed_seconds=time.time() - start_time,
            )

            # Persist
            append_analysis(market.market_id, version, analyses_path)
            candidate.narrative = narrative_output

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
        with PaperTradingDB(
            self.config.paper_trading.data_file,
            position_size_usd=self.config.paper_trading.default_position_size_usd,
            friction_pct=self.config.paper_trading.assumed_round_trip_friction_pct,
        ) as db:
            trade = db.mark(
                market_id=market_id, title=title, side=side,
                entry_price=price, market_type=market_type,
                beauty_score=score,
                scan_id=getattr(self, "last_scan_id", None),
            )
            return trade.id

    def get_paper_trades(self) -> list:
        with PaperTradingDB(self.config.paper_trading.data_file) as db:
            return db.list_open()

    def get_paper_stats(self) -> dict:
        with PaperTradingDB(self.config.paper_trading.data_file) as db:
            return db.stats()
