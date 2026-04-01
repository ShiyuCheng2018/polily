"""MarketDetailView: decision-first market analysis with AI insights."""

from datetime import UTC

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from scanner.reporting import ScoredCandidate
from scanner.tui.service import ScanService


class BackToList(Message):
    """Request to go back to market list."""
    pass


class AnalyzeRequested(Message):
    """Request MainScreen to run AI analysis."""
    def __init__(self, candidate: ScoredCandidate):
        super().__init__()
        self.candidate = candidate


class CancelAnalysisRequested(Message):
    """Request MainScreen to cancel running AI analysis."""
    pass


class SwitchVersionRequested(Message):
    """Request MainScreen to rebuild detail view at a specific version index."""
    def __init__(self, candidate: ScoredCandidate, version_idx: int, show_detail: bool = False):
        super().__init__()
        self.candidate = candidate
        self.version_idx = version_idx
        self.show_detail = show_detail


# Action level colors and labels
ACTION_DISPLAY = {
    # New schema
    "PASS": ("[red]PASS[/red]", "red"),
    "WATCH": ("[yellow]WATCH[/yellow]", "yellow"),
    "BUY_YES": ("[green]BUY YES[/green]", "green"),
    "BUY_NO": ("[green]BUY NO[/green]", "green"),
    # Legacy compat
    "avoid": ("[red]PASS[/red]", "red"),
    "watch_only": ("[yellow]WATCH[/yellow]", "yellow"),
    "worth_research": ("[cyan]RESEARCH[/cyan]", "cyan"),
    "small_position_ok": ("[green]GO[/green]", "green"),
}

CONFIDENCE_BAR = {
    "low": "[dim]██░░░░░░░░[/dim]",
    "medium": "[yellow]██████░░░░[/yellow]",
    "high": "[green]████████░░[/green]",
}

URGENCY_LABEL = {
    "urgent": "[red]紧急[/red]",
    "normal": "正常",
    "no_rush": "[dim]不急[/dim]",
}


class MarketDetailView(Widget):
    """Decision-first market detail view."""

    BINDINGS = [
        Binding("escape", "go_back", "返回列表"),
        Binding("a", "analyze", "AI分析"),
        Binding("d", "toggle_detail", show=False),
        Binding("left", "prev_version", show=False),
        Binding("right", "next_version", show=False),
        Binding("p", "mark_pass", show=False),
        Binding("w", "mark_watch", show=False),
        Binding("y", "trade_yes", "买 YES"),
        Binding("n", "trade_no", "买 NO"),
        Binding("o", "open_link", "打开链接"),
    ]

    DEFAULT_CSS = """
    MarketDetailView { height: 1fr; }
    MarketDetailView .section-title { text-style: bold; color: $primary; padding: 1 0 0 0; }
    MarketDetailView .detail-row { padding: 0 0 0 2; }
    MarketDetailView .risk-critical { color: $error; padding: 0 0 0 2; }
    MarketDetailView .risk-warning { color: $warning; padding: 0 0 0 2; }
    MarketDetailView .risk-info { color: $text-muted; padding: 0 0 0 2; }
    MarketDetailView .finding-row { padding: 0 0 0 2; color: $text; }
    MarketDetailView .finding-impact { padding: 0 0 0 4; color: $text-muted; }
    MarketDetailView .conclusion-box { padding: 1 2; margin: 1 0; }
    """

    def __init__(self, candidate: ScoredCandidate, service: ScanService,
                 analyzing: bool = False, version_idx: int | None = None,
                 show_detail: bool = False):
        super().__init__()
        self.candidate = candidate
        self.service = service
        self._analyzing = analyzing
        self._show_detail = show_detail
        self._versions = []
        self._version_idx = -1
        self._load_versions()
        if version_idx is not None and 0 <= version_idx < len(self._versions):
            self._version_idx = version_idx

    def _load_versions(self):
        from scanner.analysis_store import get_market_analyses
        self._versions = get_market_analyses(
            self.candidate.market.market_id,
            self.service.db,
        )
        if self._versions:
            self._version_idx = len(self._versions) - 1

    def _current_narrative(self):
        """Get narrative from current version or fallback to scan narrative."""
        if self._versions and self._version_idx >= 0:
            from scanner.agents.schemas import NarrativeWriterOutput
            v = self._versions[self._version_idx]
            try:
                return NarrativeWriterOutput.model_validate(v.narrative_output)
            except Exception:
                pass
        return self.candidate.narrative

    def compose(self) -> ComposeResult:
        m = self.candidate.market
        s = self.candidate.score
        mp = self.candidate.mispricing
        n = self._current_narrative()

        with VerticalScroll():
            # === TITLE + THREE SCORES ===
            days_str = f"{m.days_to_resolution:.1f}天" if m.days_to_resolution else "?"
            data_time = m.data_fetched_at.astimezone().strftime("%Y-%m-%d %H:%M:%S") if m.data_fetched_at else "?"
            yield Static(f" [bold]{m.title}[/bold]", classes="section-title")
            yield Static(f"  {m.market_type or 'other'} | 结算: {days_str} | [dim]数据: {data_time}[/dim]")
            yield from self._compose_three_scores(s)

            # === FIRST SCREEN: DECISION ZONE ===
            if self._analyzing:
                yield Static(" AI 分析中...", classes="section-title")
                yield Static("  正在联网搜索 + 分析，请稍候...", classes="detail-row")
            elif n:
                yield from self._compose_conclusion_card(n)
            else:
                yield Static("")
                yield Static("  [dim]按 a 启动 AI 分析[/dim]", classes="detail-row")

            # Risk calculator (moved up to first screen)
            yield from self._compose_risk_calculator(m)

            # Critical risks only (first screen)
            if n and not self._analyzing:
                yield from self._compose_critical_risks(n)

            # Why not + recheck (avoid/watch only, first screen)
            if n and not self._analyzing:
                yield from self._compose_why_not_and_recheck(n)

            # === SECOND SCREEN: SUPPORT ZONE ===
            if n and not self._analyzing:
                yield from self._compose_support_zone(n, m, mp)

            # === THIRD SCREEN: RESEARCH FINDINGS ===
            if n and not self._analyzing:
                yield from self._compose_research_findings(n)

            # Score breakdown (collapsible detail)
            yield from self._compose_score_detail(s)

            # Footer
            yield Static("")
            if self._versions:
                yield Static("  [dim]Esc 返回 | a 分析 | < > 版本 | p PASS | w WATCH | y YES | n NO | o 链接[/dim]")
            else:
                yield Static("  [dim]Esc 返回 | a AI分析 | p PASS | w WATCH | y YES | n NO | o 链接[/dim]")

    def _compose_conclusion_card(self, n) -> ComposeResult:
        """Decision conclusion card — the most important thing on screen."""
        # Detect if this is a rule-based fallback (no AI ran successfully)
        # Real AI output has substantive content even without supporting_findings
        supporting = getattr(n, "supporting_findings", [])
        invalidation = getattr(n, "invalidation_findings", [])
        why_not = getattr(n, "why_not_now", "") or ""
        has_substance = bool(supporting or invalidation or len(why_not) > 80)
        is_fallback = not has_substance and getattr(n, "confidence", "") == "low"
        if is_fallback:
            yield Static("  [yellow]AI 分析未成功，以下为规则估算。按 a 重试。[/yellow]", classes="detail-row")

        action_label, _ = ACTION_DISPLAY.get(getattr(n, "action", "PASS"), ("[dim]?[/dim]", "dim"))
        confidence = getattr(n, "confidence", "low")
        conf_bar = CONFIDENCE_BAR.get(confidence, CONFIDENCE_BAR["low"])

        why = getattr(n, "why_now", "") or getattr(n, "why_not_now", "")

        verdict = getattr(n, "one_line_verdict", "")
        yield Static("")
        yield Static(f"  {action_label}  {why}", classes="conclusion-box")
        if verdict:
            yield Static(f"  [dim]{verdict}[/dim]", classes="detail-row")
        yield Static(f"  置信度 {conf_bar} {confidence}", classes="detail-row")

        # Opportunity type + execution risk
        opp_type = getattr(n, "opportunity_type", "")
        exec_risk = getattr(n, "execution_risk", "")
        if opp_type and opp_type != "no_trade":
            yield Static(f"  机会类型: {opp_type} | 执行风险: {exec_risk}", classes="detail-row")

        # Friction vs edge
        fve = getattr(n, "friction_vs_edge", "")
        fve_map = {"edge_exceeds": "edge > 摩擦", "roughly_equals": "edge ≈ 摩擦", "friction_exceeds": "摩擦 > edge"}
        if fve:
            yield Static(f"  摩擦: {fve_map.get(fve, fve)}", classes="detail-row")

        # Time window
        tw = getattr(n, "time_window", None)
        if tw and hasattr(tw, "urgency"):
            urgency_label = URGENCY_LABEL.get(tw.urgency, tw.urgency)
            note = tw.note if hasattr(tw, "note") else ""
            yield Static(f"  窗口: {urgency_label} | {note}", classes="detail-row")

        # Next step
        next_step = getattr(n, "next_step", "")
        if next_step:
            yield Static(f"  下一步: {next_step}", classes="detail-row")

        # Version selector
        if self._versions:
            v = self._versions[self._version_idx]
            total = len(self._versions)
            idx = self._version_idx + 1
            ts = v.created_at[5:16].replace("T", " ")
            price_note = f"@{v.yes_price_at_analysis:.2f}" if v.yes_price_at_analysis else ""
            yield Static(
                f"  [dim]v{v.version} ({ts}) {price_note}  < > 切换版本 ({idx}/{total})[/dim]",
                classes="detail-row",
            )

        # Bias + strength
        bias = getattr(n, "bias", "NONE")
        strength = getattr(n, "strength", "")
        if bias and bias not in ("NONE", "neutral", None):
            bias_cn = {"YES": "偏 YES", "NO": "偏 NO"}.get(str(bias), str(bias))
            strength_str = f" ({strength})" if strength else ""
            yield Static(f"  方向: {bias_cn}{strength_str}", classes="detail-row")

    def _compose_risk_calculator(self, m) -> ComposeResult:
        """Scenario calculator with explanations."""
        if m.yes_price and m.yes_price > 0:
            pos = 20.0
            friction_pct = m.round_trip_friction_pct or 0.04
            friction_cost = pos * friction_pct
            profit = (pos / m.yes_price) * 1.0 - pos
            net_profit = profit - friction_cost
            yield Static("")
            yield Static("  $20 投入:", classes="detail-row")
            yield Static(f"    最坏 -${pos:.0f}       [dim]全亏（结算为反方向）[/dim]", classes="detail-row")
            yield Static(f"    摩擦 -${friction_cost:.2f}     [dim]买卖价差成本 ({friction_pct:.1%})[/dim]", classes="detail-row")
            yield Static(f"    判断对 +${net_profit:.2f}   [dim]结算正确时净利润（扣摩擦）[/dim]", classes="detail-row")

    def _compose_critical_risks(self, n) -> ComposeResult:
        """Only show severity=critical risks in first screen."""
        risk_flags = getattr(n, "risk_flags", [])
        critical = []
        for rf in risk_flags:
            if hasattr(rf, "severity") and rf.severity == "critical":
                critical.append(rf.text)
            elif isinstance(rf, str):
                critical.append(rf)  # backward compat with old format
        if critical:
            yield Static("")
            for text in critical[:2]:
                yield Static(f"  ! {text}", classes="risk-critical")

    def _compose_why_not_and_recheck(self, n) -> ComposeResult:
        """Why not now + recheck conditions (PASS/WATCH only)."""
        action = getattr(n, "action", "")
        if action not in ("PASS", "WATCH", "avoid", "watch_only"):
            return

        why_not_now = getattr(n, "why_not_now", "")
        recheck = getattr(n, "recheck_conditions", [])

        if why_not_now:
            yield Static(" 不做的理由", classes="section-title")
            yield Static(f"  {why_not_now}", classes="detail-row")

        if recheck:
            yield Static(" 什么情况下值得再看", classes="section-title")
            for cond in recheck[:3]:
                yield Static(f"  - {cond}", classes="detail-row")

    def _compose_support_zone(self, n, m, mp) -> ComposeResult:
        """Second screen: AI summary + counterparty + price + mispricing."""
        # AI summary
        if getattr(n, "summary", ""):
            yield Static(" AI 分析", classes="section-title")
            yield Static(f"  {getattr(n, 'summary', '')}", classes="detail-row")

        # Counterparty
        counterparty = getattr(n, "counterparty_note", "")
        if counterparty:
            yield Static(" 对手方", classes="section-title")
            yield Static(f"  {counterparty}", classes="detail-row")

        # Crypto context (if available)
        crypto = getattr(n, "crypto", None)
        if crypto and hasattr(crypto, "buffer_conclusion"):
            yield Static(" Crypto 分析", classes="section-title")
            if crypto.distance_to_threshold_pct is not None:
                yield Static(f"  距阈值: {crypto.distance_to_threshold_pct:.1f}%", classes="detail-row")
            if crypto.buffer_pct is not None and crypto.daily_vol_pct is not None:
                yield Static(f"  安全垫: {crypto.buffer_pct:.1f}% | 日波动: {crypto.daily_vol_pct:.1f}% | {crypto.buffer_conclusion}", classes="detail-row")
            if crypto.market_already_knows:
                yield Static(f"  [dim]{crypto.market_already_knows}[/dim]", classes="detail-row")

        # Price info
        yield Static(" 价格", classes="section-title")
        yield Static(f"  YES: {m.yes_price:.2f} | NO: {m.no_price or 0:.2f}", classes="detail-row")
        spread = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
        friction = f"{m.round_trip_friction_pct:.1%}" if m.round_trip_friction_pct else "?"
        yield Static(f"  价差: {spread} | 摩擦: {friction}", classes="detail-row")
        bid = f"${m.total_bid_depth_usd:,.0f}" if m.total_bid_depth_usd else "?"
        ask = f"${m.total_ask_depth_usd:,.0f}" if m.total_ask_depth_usd else "?"
        yield Static(f"  深度: 买 {bid} / 卖 {ask}", classes="detail-row")

        # Mispricing
        if mp.signal != "none":
            yield Static(" 定价偏差", classes="section-title")
            yield Static(f"  {mp.signal.upper()} | {mp.details or ''}", classes="detail-row")

        # All risks (including warning/info)
        risk_flags = getattr(n, "risk_flags", [])
        non_critical = []
        for rf in risk_flags:
            if hasattr(rf, "severity"):
                if rf.severity != "critical":
                    non_critical.append((rf.text, rf.severity))
            elif isinstance(rf, str):
                non_critical.append((rf, "warning"))
        if non_critical:
            yield Static(" 其他风险", classes="section-title")
            for text, severity in non_critical:
                css_class = f"risk-{severity}"
                yield Static(f"  ! {text}", classes=css_class)

    def _compose_research_findings(self, n) -> ComposeResult:
        """Third screen: supporting + invalidation findings."""
        supporting = getattr(n, "supporting_findings", [])
        invalidation = getattr(n, "invalidation_findings", [])
        # Legacy compat
        all_findings = []
        if supporting:
            all_findings.append(("依据", supporting))
        if invalidation:
            all_findings.append(("可能判断错的地方", invalidation))

        for section_title, findings in all_findings:
            yield Static(f" {section_title}", classes="section-title")
            for f in findings:
                if hasattr(f, "finding"):
                    source = f"[dim]来源: {f.source}[/dim]" if f.source else ""
                    yield Static(f"  {f.finding}  {source}", classes="finding-row")
                    if f.impact:
                        yield Static(f"    -> {f.impact}", classes="finding-impact")
                elif isinstance(f, dict):
                    yield Static(f"  {f.get('finding', '')}  [dim]{f.get('source', '')}[/dim]", classes="finding-row")
                    impact = f.get("impact", "")
                    if impact:
                        yield Static(f"    -> {impact}", classes="finding-impact")

    def _compose_three_scores(self, s) -> ComposeResult:
        """Three-score bar gauges — shown right below title."""
        from scanner.scoring import compute_three_scores
        three = compute_three_scores(s, self.candidate.mispricing, self.candidate.market)

        def bar(val, label):
            if val is None:
                return f"{label} [dim]N/A[/dim]"
            filled = int(val / 100 * 8)
            return f"{label} {'█' * filled}{'░' * (8 - filled)} {val:.0f}"

        q_bar = bar(three["quality"], "质量")
        v_bar = bar(three["value"], "价值")
        e_bar = bar(three["edge"], "方向")
        yield Static(f"  {q_bar}   {v_bar}   {e_bar}")

    def _compose_score_detail(self, s) -> ComposeResult:
        """5-item score breakdown with explanations — collapsible."""
        m = self.candidate.market
        if self._show_detail:
            # Build explanations from actual market data
            spread = m.spread_pct_yes
            bid = m.total_bid_depth_usd
            liq_parts = []
            if spread is not None:
                liq_parts.append(f"价差 {spread:.1%}")
            if bid is not None:
                liq_parts.append(f"买深 ${bid:,.0f}")
            liq_note = "，".join(liq_parts) if liq_parts else "无深度数据"

            import re as _re
            res_src = m.resolution_source
            if not res_src:
                # Check rules/description text for resolution source mention
                rules_text = (m.rules or "") + " " + (m.description or "")
                match = _re.search(r"resolution source.*?\bis\b\s+(\w+)", rules_text, _re.IGNORECASE)
                if match:
                    res_src = match.group(1)
                elif _re.search(r"resolves? to .yes.", rules_text, _re.IGNORECASE):
                    res_src = "(规则文本中)"
            obj_note = f"结算来源: {res_src[:30]}" if res_src else "结算标准不明确"

            p = m.yes_price or 0
            prob_note = f"YES {p:.2f}"
            if 0.30 <= p <= 0.70:
                prob_note += "，在甜蜜区"
            elif p < 0.15 or p > 0.85:
                prob_note += "，极端概率"

            days = m.days_to_resolution
            time_note = f"距结算 {days:.1f} 天" if days else "结算时间未知"
            if days and 1.0 <= days <= 5.0:
                time_note += "，最佳窗口"

            friction_pct = m.round_trip_friction_pct
            fric_note = f"来回 {friction_pct:.1%}" if friction_pct else "摩擦未知"

            explanations = {
                "流动性结构": liq_note,
                "客观验证": obj_note,
                "概率空间": prob_note,
                "时间结构": time_note,
                "交易摩擦": fric_note,
            }

            for name, val, mx in [
                ("流动性结构", s.liquidity_structure, 30),
                ("客观验证", s.objective_verifiability, 25),
                ("概率空间", s.probability_space, 20),
                ("时间结构", s.time_structure, 15),
                ("交易摩擦", s.trading_friction, 10),
            ]:
                bar_len = int(val / mx * 10) if mx > 0 else 0
                bar_str = "█" * bar_len + "░" * (10 - bar_len)
                note = explanations.get(name, "")
                yield Static(f"  {name:6s} {bar_str} {val:.1f}/{mx}  [dim]{note}[/dim]", classes="detail-row")
            yield Static(f"  [bold]总分: {s.total:.0f}/100[/bold]  [dim]按 d 收起[/dim]", classes="detail-row")
        else:
            # Collapsed: single line
            parts = []
            for name, val, mx in [
                ("流动", s.liquidity_structure, 30), ("客观", s.objective_verifiability, 25),
                ("概率", s.probability_space, 20), ("时间", s.time_structure, 15),
                ("摩擦", s.trading_friction, 10),
            ]:
                pct = int(val / mx * 100) if mx > 0 else 0
                parts.append(f"{name}:{pct}%")
            yield Static(f"  {' | '.join(parts)}  [dim]按 d 展开[/dim]", classes="detail-row")

    # === Actions ===

    def action_toggle_detail(self) -> None:
        self.post_message(SwitchVersionRequested(
            self.candidate, self._version_idx, show_detail=not self._show_detail,
        ))

    def action_go_back(self) -> None:
        if self._analyzing:
            self.post_message(CancelAnalysisRequested())
        else:
            self.post_message(BackToList())

    def action_analyze(self) -> None:
        if self._analyzing:
            return
        self._analyzing = True
        self.post_message(AnalyzeRequested(self.candidate))

    def action_prev_version(self) -> None:
        if self._versions and self._version_idx > 0:
            self.post_message(SwitchVersionRequested(self.candidate, self._version_idx - 1))

    def action_next_version(self) -> None:
        if self._versions and self._version_idx < len(self._versions) - 1:
            self.post_message(SwitchVersionRequested(self.candidate, self._version_idx + 1))

    def action_trade_yes(self) -> None:
        self._do_trade("yes")

    def action_trade_no(self) -> None:
        self._do_trade("no")

    def _do_trade(self, side: str):
        m = self.candidate.market
        if side == "yes":
            price = m.yes_price
        else:
            price = m.no_price if m.no_price is not None else (1 - (m.yes_price or 0.5))
        if not price or price <= 0:
            return

        pending = getattr(self, "_pending_trade", None)
        if pending == (m.market_id, side):
            trade_id = self.service.mark_paper_trade(
                market_id=m.market_id, title=m.title, side=side,
                price=price, market_type=m.market_type, score=self.candidate.score.total,
            )
            self.notify(f"Paper trade: {side.upper()} @ {price:.2f} -> {trade_id}")
            self._pending_trade = None
            self.screen.refresh_sidebar_counts()
        else:
            self._pending_trade = (m.market_id, side)
            title_short = m.title[:30]
            self.notify(f"再按一次 {side[0]} 确认: {side.upper()} {title_short} @ {price:.2f}")

    def action_mark_pass(self) -> None:
        """Mark this market as PASS — won't appear in research queue."""
        from datetime import datetime

        from scanner.market_state import MarketState, set_market_state
        state = MarketState(status="pass", updated_at=datetime.now(UTC).isoformat(),
                            title=self.candidate.market.title)
        set_market_state(self.candidate.market.market_id, state, self.service.db)
        self.notify(f"PASS: {self.candidate.market.title[:30]}")
        self.screen.refresh_sidebar_counts()

    def action_mark_watch(self) -> None:
        """Add to watch list with conditions from AI narrative."""
        from datetime import datetime

        from scanner.market_state import MarketState, set_market_state
        n = self._current_narrative()
        watch_cond = getattr(n, "watch", None) if n else None
        if not watch_cond:
            self.notify("请先按 a 进行 AI 分析", severity="warning")
            return
        state = MarketState(
            status="watch",
            updated_at=datetime.now(UTC).isoformat(),
            title=self.candidate.market.title,
            wc_watch_reason=watch_cond.watch_reason,
            wc_better_entry=watch_cond.better_entry,
            wc_trigger_event=watch_cond.trigger_event,
            wc_invalidation=watch_cond.invalidation,
            next_check_at=getattr(watch_cond, "next_check_at", None),
            watch_reason=getattr(watch_cond, "reason", None),
            price_at_watch=self.candidate.market.yes_price,
            resolution_time=(self.candidate.market.resolution_time.isoformat()
                           if self.candidate.market.resolution_time else None),
        )
        set_market_state(self.candidate.market.market_id, state, self.service.db)
        self.notify(f"WATCH: {self.candidate.market.title[:30]}")
        self.screen.refresh_sidebar_counts()

    def action_open_link(self) -> None:
        import webbrowser
        try:
            webbrowser.open(self.candidate.market.polymarket_url)
        except Exception:
            self.notify("无法打开浏览器", severity="warning")
