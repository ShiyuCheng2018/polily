"""MarketDetailView: full market analysis with score breakdown, risks, actions."""

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
    def __init__(self, candidate: ScoredCandidate, version_idx: int):
        super().__init__()
        self.candidate = candidate
        self.version_idx = version_idx


class MarketDetailView(Widget):
    """Full detail view for a single market candidate."""

    BINDINGS = [
        Binding("escape", "go_back", "返回列表"),
        Binding("a", "analyze", "AI分析"),
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
    MarketDetailView .risk-item { color: $error; padding: 0 0 0 2; }
    MarketDetailView .checklist-item { color: $text-muted; padding: 0 0 0 2; }
    """

    def __init__(self, candidate: ScoredCandidate, service: ScanService,
                 analyzing: bool = False, version_idx: int | None = None):
        super().__init__()
        self.candidate = candidate
        self.service = service
        self._analyzing = analyzing
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

        with VerticalScroll():
            # Title
            resolution_str = f" | 结算: {m.days_to_resolution:.1f}天" if m.days_to_resolution else ""
            yield Static(f" [bold]{m.title}[/bold]", classes="section-title")
            yield Static(f"  类型: {m.market_type or '?'}{resolution_str}")
            yield Static("  按 o 打开 Polymarket")

            # Prices
            yield Static(" 价格信息", classes="section-title")
            yield Static(f"  YES: {m.yes_price:.2f} | NO: {m.no_price or 0:.2f}", classes="detail-row")
            spread = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
            friction = f"{m.round_trip_friction_pct:.1%}" if m.round_trip_friction_pct else "?"
            w_spread = Static(f"  价差: {spread} | 摩擦: {friction}", classes="detail-row")
            w_spread.tooltip = "价差: 买卖价之间的差距 | 摩擦: 一买一卖的总成本估算"
            yield w_spread
            bid = f"${m.total_bid_depth_usd:,.0f}" if m.total_bid_depth_usd else "?"
            ask = f"${m.total_ask_depth_usd:,.0f}" if m.total_ask_depth_usd else "?"
            w_depth = Static(f"  深度: 买 {bid} / 卖 {ask}", classes="detail-row")
            w_depth.tooltip = "订单簿深度: 买方/卖方挂单总金额，越大越容易成交"
            yield w_depth

            # Score breakdown
            yield Static(" 结构评分明细", classes="section-title")
            score_tooltips = {
                "结算时间": "距离市场结算的时间，0.5-7天最佳",
                "客观性":   "结算标准是否明确可验证",
                "概率区间": "当前价格是否在 0.30-0.70 区间，太极端的没有交易价值",
                "流动性":   "买卖盘深度 + 价差，决定能否以合理价格成交",
                "可退出性": "卖出时买方深度是否足够，决定能否顺利退出",
                "催化剂":   "是否有明确的事件驱动（如数据发布、比赛结果）",
                "小账户":   "$20 仓位下的摩擦成本是否可接受",
            }
            for name, val, max_val in [
                ("结算时间", s.time_to_resolution, 15),
                ("客观性", s.objectivity, 20),
                ("概率区间", s.probability_zone, 20),
                ("流动性", s.liquidity_depth, 20),
                ("可退出性", s.exitability, 10),
                ("催化剂", s.catalyst_proxy, 5),
                ("小账户", s.small_account_friendliness, 10),
            ]:
                bar_len = int(val / max_val * 10) if max_val > 0 else 0
                bar = "█" * bar_len + "░" * (10 - bar_len)
                w = Static(f"  {name:8s} {bar} {val:.1f}/{max_val}", classes="detail-row")
                w.tooltip = score_tooltips.get(name, "")
                yield w
            yield Static(f"  [bold]总分: {s.total:.0f}/100[/bold]", classes="detail-row")

            # Mispricing
            if mp.signal != "none":
                w_mp_title = Static(" 定价偏差", classes="section-title")
                w_mp_title.tooltip = "基于数学模型（对数正态波动率）检测市场价格是否偏离理论值"
                yield w_mp_title
                yield Static(f"  信号: {mp.signal.upper()} | {mp.details or ''}", classes="detail-row")

            # AI Analysis — version selector + content
            if self._analyzing:
                yield Static(" AI 分析中...", classes="section-title")
                yield Static("  请稍候，正在调用 AI agent...", classes="detail-row")
            else:
                n = self._current_narrative()

                # Version selector
                if self._versions:
                    v = self._versions[self._version_idx]
                    total = len(self._versions)
                    idx = self._version_idx + 1
                    ts = v.created_at[5:16].replace("T", " ")
                    price_note = f"@{v.yes_price_at_analysis:.2f}" if v.yes_price_at_analysis else ""
                    yield Static(
                        f" AI 分析  [bold]v{v.version}[/bold] ({ts}) {price_note}"
                        f"  [dim]< > 切换版本 ({idx}/{total})[/dim]",
                        classes="section-title",
                    )
                elif n:
                    yield Static(" AI 分析", classes="section-title")

                if n:
                    yield Static(f"  {n.summary}", classes="detail-row")

                    if n.risk_flags:
                        yield Static(" 风险提示", classes="section-title")
                        for flag in n.risk_flags:
                            yield Static(f"  ! {flag}", classes="risk-item")

                    if n.counterparty_note:
                        yield Static(" 对手方", classes="section-title")
                        yield Static(f"  {n.counterparty_note}", classes="detail-row")

                    if n.research_checklist:
                        yield Static(" 研究清单", classes="section-title")
                        for item in n.research_checklist:
                            yield Static(f"  □ {item}", classes="checklist-item")

            # Scenario calculator
            if m.yes_price and m.yes_price > 0:
                pos = 20.0
                friction_cost = pos * (m.round_trip_friction_pct or 0.04)
                profit = (pos / m.yes_price) * 1.0 - pos
                yield Static(" 风险计算 ($20)", classes="section-title")
                w_risk = Static(f"  最坏: -${pos:.0f} | 摩擦: -${friction_cost:.2f} | 判断对: +${profit - friction_cost:.2f}", classes="detail-row")
                w_risk.tooltip = "最坏: 全亏 | 摩擦: 买卖价差成本 | 判断对: 结算为YES时的净利润"
                yield w_risk

            yield Static("")
            if self._versions:
                yield Static("  [dim]Esc 返回 | a 重新分析 | < > 切换版本 | y YES | n NO | o 链接[/dim]")
            else:
                yield Static("  [dim]Esc 返回 | a AI分析 | y 买YES | n 买NO | o 打开链接[/dim]")

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

        # Double-press confirm
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
