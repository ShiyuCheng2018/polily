"""MarketDetailView: decision-first market analysis with AI insights."""

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


class SwitchVersionRequested(Message):
    """Request MainScreen to rebuild detail view at a specific version index."""
    def __init__(self, candidate: ScoredCandidate, version_idx: int, show_detail: bool = False):
        super().__init__()
        self.candidate = candidate
        self.version_idx = version_idx
        self.show_detail = show_detail


# Action level colors and labels
ACTION_DISPLAY = {
    "avoid": ("[red]AVOID[/red]", "red"),
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
            self.service.config.archiving.analyses_file,
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
            yield Static(f" [bold]{m.title}[/bold]", classes="section-title")
            yield Static(f"  {m.market_type or 'other'} | 结算: {days_str}")
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
                yield Static("  [dim]Esc 返回 | a 重新分析 | < > 切换版本 | y YES | n NO | o 链接[/dim]")
            else:
                yield Static("  [dim]Esc 返回 | a AI分析 | y YES | n NO | o 链接[/dim]")

    def _compose_conclusion_card(self, n) -> ComposeResult:
        """Decision conclusion card — the most important thing on screen."""
        action_label, _ = ACTION_DISPLAY.get(getattr(n, "action", "watch_only"), ("[dim]?[/dim]", "dim"))
        confidence = getattr(n, "confidence", "low")
        conf_bar = CONFIDENCE_BAR.get(confidence, CONFIDENCE_BAR["low"])
        action_reasoning = getattr(n, "action_reasoning", "")
        friction_impact = getattr(n, "friction_impact", "")

        verdict = getattr(n, "one_line_verdict", "")
        yield Static("")
        yield Static(f"  {action_label}  {action_reasoning}", classes="conclusion-box")
        if verdict:
            yield Static(f"  [dim]{verdict}[/dim]", classes="detail-row")
        yield Static(f"  置信度 {conf_bar} {confidence}", classes="detail-row")

        # Time window
        tw = getattr(n, "time_window", None)
        if tw and hasattr(tw, "urgency"):
            urgency_label = URGENCY_LABEL.get(tw.urgency, tw.urgency)
            note = tw.note if hasattr(tw, "note") else ""
            yield Static(f"  窗口: {urgency_label} | {note}", classes="detail-row")

        if friction_impact:
            yield Static(f"  摩擦: {friction_impact}", classes="detail-row")

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

        # Bias (only if available — lean mode)
        bias = getattr(n, "bias", None)
        if bias and hasattr(bias, "direction") and bias.direction != "neutral":
            direction_cn = {"lean_yes": "偏 YES", "lean_no": "偏 NO"}.get(bias.direction, "?")
            yield Static(f"  方向: {direction_cn} ({bias.caveat})", classes="detail-row")

    def _compose_risk_calculator(self, m) -> ComposeResult:
        """Scenario calculator — moved to first screen for quick decision."""
        if m.yes_price and m.yes_price > 0:
            pos = 20.0
            friction_cost = pos * (m.round_trip_friction_pct or 0.04)
            profit = (pos / m.yes_price) * 1.0 - pos
            yield Static("")
            yield Static(
                f"  $20 投入: 最坏 -${pos:.0f} | 摩擦 -${friction_cost:.2f} | 判断对 +${profit - friction_cost:.2f}",
                classes="detail-row",
            )

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
        """Third screen: agent's own research results."""
        findings = getattr(n, "research_findings", [])
        # Backward compat: old format had research_checklist
        checklist = getattr(n, "research_checklist", []) if not findings else []

        if findings:
            yield Static(" 研究发现", classes="section-title")
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
        elif checklist:
            # Backward compat for old analyses
            yield Static(" 研究清单", classes="section-title")
            for item in checklist:
                yield Static(f"  {item}", classes="detail-row")

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
        """7-item score breakdown — collapsible."""
        if self._show_detail:
            # Expanded: 7-item bar chart
            for name, val, mx in [
                ("结算时间", s.time_to_resolution, 15),
                ("客观性", s.objectivity, 20),
                ("概率区间", s.probability_zone, 20),
                ("流动性", s.liquidity_depth, 20),
                ("可退出性", s.exitability, 10),
                ("催化剂", s.catalyst_proxy, 5),
                ("小账户", s.small_account_friendliness, 10),
            ]:
                bar_len = int(val / mx * 10) if mx > 0 else 0
                bar_str = "█" * bar_len + "░" * (10 - bar_len)
                yield Static(f"  {name:8s} {bar_str} {val:.1f}/{mx}", classes="detail-row")
            yield Static(f"  [bold]总分: {s.total:.0f}/100[/bold]  [dim]按 d 收起[/dim]", classes="detail-row")
        else:
            # Collapsed: single line
            parts = []
            for name, val, mx in [
                ("时间", s.time_to_resolution, 15), ("客观", s.objectivity, 20),
                ("概率", s.probability_zone, 20), ("流动", s.liquidity_depth, 20),
                ("退出", s.exitability, 10), ("催化", s.catalyst_proxy, 5),
                ("小户", s.small_account_friendliness, 10),
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

    def action_open_link(self) -> None:
        import webbrowser
        try:
            webbrowser.open(self.candidate.market.polymarket_url)
        except Exception:
            self.notify("无法打开浏览器", severity="warning")
