"""MarketDetailView: dashboard-style market analysis with AI insights."""

from datetime import UTC

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalGroup, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from scanner.reporting import ScoredCandidate
from scanner.tui.service import ScanService
from scanner.tui.widgets.cards import DashPanel, MetricCard


class BackToList(Message):
    pass


class AnalyzeRequested(Message):
    def __init__(self, candidate: ScoredCandidate):
        super().__init__()
        self.candidate = candidate


class CancelAnalysisRequested(Message):
    pass


class SwitchVersionRequested(Message):
    def __init__(self, candidate: ScoredCandidate, version_idx: int, show_detail: bool = False):
        super().__init__()
        self.candidate = candidate
        self.version_idx = version_idx
        self.show_detail = show_detail


# Action level colors and labels
ACTION_DISPLAY = {
    "PASS": ("[red]PASS[/red]", "red"),
    "WATCH": ("[yellow]WATCH[/yellow]", "yellow"),
    "BUY_YES": ("[green]BUY YES[/green]", "green"),
    "BUY_NO": ("[green]BUY NO[/green]", "green"),
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
    """Dashboard-style market detail view."""

    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("a", "analyze", "AI分析"),
        Binding("d", "toggle_detail", show=False),
        Binding("left", "prev_version", show=False),
        Binding("right", "next_version", show=False),
        Binding("p", "mark_pass", "PASS"),
        Binding("m", "toggle_auto_monitor", "监控"),
        Binding("y", "trade_yes", "YES"),
        Binding("n", "trade_no", "NO"),
        Binding("o", "open_link", "链接"),
    ]

    DEFAULT_CSS = """
    MarketDetailView { height: 1fr; }
    MarketDetailView .header-title { text-style: bold; color: $primary; padding: 1 0 0 1; }
    MarketDetailView .header-sub { color: $text-muted; padding: 0 0 0 2; }
    MarketDetailView .panel-row { padding: 0 0 0 1; }
    MarketDetailView .panel-label { color: $text-muted; padding: 0 0 0 1; }
    MarketDetailView .panel-value { padding: 0 0 0 1; }
    MarketDetailView .risk-critical { color: $error; padding: 0 0 0 1; }
    MarketDetailView .risk-warning { color: $warning; padding: 0 0 0 1; }
    MarketDetailView .risk-info { color: $text-muted; padding: 0 0 0 1; }
    MarketDetailView .finding-row { padding: 0 0 0 1; color: $text; }
    MarketDetailView .finding-impact { padding: 0 0 0 3; color: $text-muted; }
    MarketDetailView .section-label { text-style: bold; color: $primary; padding: 1 0 0 1; }
    MarketDetailView .fallback-warn { color: $warning; padding: 0 0 0 1; }

    MarketDetailView #kpi-row {
        height: auto;
        min-height: 5;
        padding: 0;
    }
    MarketDetailView #kpi-row MetricCard {
        height: 5;
        margin: 0 1;
    }
    MarketDetailView #decision-zone {
        height: auto;
        min-height: 10;
    }
    MarketDetailView #decision-zone DashPanel {
        width: 1fr;
        margin: 0 1;
        height: auto;
    }
    MarketDetailView #evidence-zone {
        height: auto;
        min-height: 8;
    }
    MarketDetailView #evidence-zone DashPanel {
        width: 1fr;
        margin: 0 1;
        height: auto;
    }
    MarketDetailView #score-bar {
        height: 1;
        background: $primary-background;
        color: $text;
        padding: 0 1;
    }
    MarketDetailView #footer-hint {
        height: 1;
        color: $text-muted;
        padding: 0 1;
    }
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
        self._pending_trade: tuple | None = None
        self._load_versions()
        if version_idx is not None and 0 <= version_idx < len(self._versions):
            self._version_idx = version_idx

    def _load_versions(self):
        from scanner.analysis_store import get_market_analyses
        self._versions = get_market_analyses(
            self.candidate.market.market_id, self.service.db)
        if self._versions:
            self._version_idx = len(self._versions) - 1

    def _current_narrative(self):
        if self._versions and self._version_idx >= 0:
            from scanner.agents.schemas import NarrativeWriterOutput
            v = self._versions[self._version_idx]
            try:
                return NarrativeWriterOutput.model_validate(v.narrative_output)
            except Exception:
                pass
        return self.candidate.narrative

    def on_mount(self) -> None:
        self._fill_kpi_cards()
        self._live_timer = self.set_interval(5, self._update_kpi)

    # ===================== COMPOSE =====================

    def compose(self) -> ComposeResult:
        m = self.candidate.market
        s = self.candidate.score
        mp = self.candidate.mispricing
        n = self._current_narrative()

        with VerticalScroll():
            # === HEADER ===
            from scanner.tui.utils import format_countdown
            res_time = m.resolution_time.isoformat() if m.resolution_time else None
            deadline_str = format_countdown(res_time)
            monitor_str = self._get_monitor_str(m.market_id)
            yield Static(f"[bold]{m.title}[/bold]", classes="header-title")
            yield Static(f"{m.market_type or 'other'} | 结算: {deadline_str} | {monitor_str}", classes="header-sub")

            # === KPI CARD ROW ===
            with HorizontalGroup(id="kpi-row"):
                yes_card = MetricCard(id="kpi-yes")
                yes_card.border_title = "YES"
                yield yes_card
                no_card = MetricCard(id="kpi-no")
                no_card.border_title = "NO"
                yield no_card
                move_card = MetricCard(id="kpi-movement")
                move_card.border_title = "异动"
                yield move_card
                time_card = MetricCard(id="kpi-time")
                time_card.border_title = "结算"
                yield time_card
                score_card = MetricCard(id="kpi-score")
                score_card.border_title = "评分"
                yield score_card

            # === ANALYZING STATE ===
            if self._analyzing:
                yield Static("AI 分析中...", classes="section-label")
                yield Static("正在联网搜索 + 分析，请稍候...", classes="panel-row")
            elif n:
                # === DECISION ZONE (two columns) ===
                yield from self._compose_decision_zone(n, m, mp)

                # === EVIDENCE ZONE (two columns) ===
                yield from self._compose_evidence_zone(n, m)
            else:
                yield Static("")
                yield Static("[dim]按 a 启动 AI 分析[/dim]", classes="panel-row")

            # === SCORE BAR ===
            yield from self._compose_score_bar(s)

            # === FOOTER ===
            yield Static(
                "[dim]Esc 返回 | a 分析 | < > 版本 | d 评分详情 | p PASS | m 监控 | y YES | n NO | o 链接[/dim]",
                id="footer-hint",
            )

    # ===================== KPI CARDS =====================

    def _get_monitor_str(self, market_id: str) -> str:
        from scanner.market_state import get_market_state
        state = get_market_state(market_id, self.service.db)
        if state and state.auto_monitor:
            return "[green]● 自动监控 ON[/green]"
        return "[dim]自动监控 OFF[/dim]"

    def _fill_kpi_cards(self) -> None:
        """Fill KPI cards with initial data."""
        m = self.candidate.market
        s = self.candidate.score

        # YES/NO from analysis snapshot
        yes_price = m.yes_price or 0
        no_price = m.no_price or (1 - yes_price if yes_price else 0)

        self._set_card("kpi-yes", f"{yes_price:.3f}")
        self._set_card("kpi-no", f"{no_price:.3f}")
        self._set_card("kpi-movement", "[dim]--[/dim]")

        from scanner.tui.utils import format_countdown
        res_time = m.resolution_time.isoformat() if m.resolution_time else None
        self._set_card("kpi-time", format_countdown(res_time))

        from scanner.scoring import compute_three_scores
        three = compute_three_scores(s, self.candidate.mispricing, m)
        q = three.get("quality")
        v = three.get("value")
        q_str = f"{q:.0f}" if q is not None else "?"
        v_str = f"{v:.0f}" if v is not None else "?"
        self._set_card("kpi-score", f"结构{q_str}\nedge{v_str}")

        # Try live data
        self._update_kpi()

    def _update_kpi(self) -> None:
        """Timer callback: refresh KPI cards from movement_log."""
        from scanner.market_state import get_market_state
        from scanner.movement_store import get_price_status

        mid = self.candidate.market.market_id
        state = get_market_state(mid, self.service.db)
        watch_price = state.price_at_watch if state else None
        status = get_price_status(mid, self.service.db, watch_price=watch_price)
        if status is None:
            return

        yes = status["current_price"]
        no = round(1 - yes, 3) if yes else 0
        change = status["change_pct"]
        no_change = -change

        def fmt_change(c):
            if c > 0:
                return f"[green]+{c:.1f}%[/green]"
            elif c < 0:
                return f"[red]{c:.1f}%[/red]"
            return "0.0%"

        self._set_card("kpi-yes", f"{yes:.3f}\n{fmt_change(change)}")
        self._set_card("kpi-no", f"{no:.3f}\n{fmt_change(no_change)}")

        mag = status["magnitude"]
        qual = status["quality"]
        label = status["label"]
        label_colors = {"consensus": "green", "whale_move": "yellow", "slow_build": "cyan", "noise": "dim"}
        lc = label_colors.get(label, "dim")
        self._set_card("kpi-movement", f"M={mag:.0f} Q={qual:.0f}\n[{lc}]{label}[/{lc}]")

        # Divergence warning on YES card
        analysis_price = self.candidate.market.yes_price
        if analysis_price and analysis_price > 0:
            div_pct = (yes - analysis_price) / analysis_price * 100
            if abs(div_pct) >= 5.0:
                self._set_card("kpi-yes", f"{yes:.3f} {fmt_change(change)}\n[yellow]⚠ 偏离{abs(div_pct):.0f}%[/yellow]")

        # Refresh countdown
        from scanner.tui.utils import format_countdown
        m = self.candidate.market
        res_time = m.resolution_time.isoformat() if m.resolution_time else None
        self._set_card("kpi-time", format_countdown(res_time))

        # Realtime score recalculation using latest market data
        self._update_realtime_scores(status)

    def _update_realtime_scores(self, status: dict) -> None:
        """Recalculate structure score + three scores from live data."""


        from scanner.models import BookLevel
        from scanner.scoring import compute_structure_score, compute_three_scores

        m = self.candidate.market
        yes = status["current_price"]
        sp = status.get("spread")

        # Compute best_bid/ask from spread for computed properties
        best_bid = yes - sp / 2 if sp else m.best_bid_yes
        best_ask = yes + sp / 2 if sp else m.best_ask_yes

        bid_d = status.get("bid_depth", 0)
        ask_d = status.get("ask_depth", 0)

        # Build a fresh Market with live data (avoids computed property setter issues)
        live = m.model_copy(update={
            "yes_price": yes,
            "no_price": round(1 - yes, 4) if yes else m.no_price,
            "best_bid_yes": best_bid,
            "best_ask_yes": best_ask,
            "book_depth_bids": [BookLevel(price=1.0, size=bid_d)] if bid_d > 0 else m.book_depth_bids,
            "book_depth_asks": [BookLevel(price=1.0, size=ask_d)] if ask_d > 0 else m.book_depth_asks,
        })

        try:
            score = compute_structure_score(live, self.service.config.scoring.weights)
            three = compute_three_scores(score, self.candidate.mispricing, live)

            q = three.get("quality")
            v = three.get("value")
            q_str = f"{q:.0f}" if q is not None else "?"
            v_str = f"{v:.0f}" if v is not None else "?"
            self._set_card("kpi-score", f"结构 {q_str}\nedge {v_str}")

            # Update score bar
            parts = []
            for name, val, mx in [
                ("流动", score.liquidity_structure, 30), ("客观", score.objective_verifiability, 25),
                ("概率", score.probability_space, 20), ("时间", score.time_structure, 15),
                ("摩擦", score.trading_friction, 10),
            ]:
                pct = int(val / mx * 100) if mx > 0 else 0
                parts.append(f"{name}:{pct}%")
            import contextlib
            with contextlib.suppress(Exception):
                self.query_one("#score-bar", Static).update(
                    f" {' | '.join(parts)} | [bold]总分:{score.total:.0f}[/bold]"
                )
        except Exception:
            pass

    def _set_card(self, card_id: str, content: str) -> None:
        import contextlib
        with contextlib.suppress(Exception):
            self.query_one(f"#{card_id}", MetricCard).update(content)

    # ===================== DECISION ZONE =====================

    def _compose_decision_zone(self, n, m, mp) -> ComposeResult:
        with Horizontal(id="decision-zone"):
            # Left: AI Decision
            panel_left = DashPanel(id="panel-decision")
            panel_left.border_title = "AI 决策"
            with panel_left:
                yield from self._render_decision(n)

            # Right: Risk & Numbers
            panel_right = DashPanel(id="panel-risk")
            panel_right.border_title = "投入与风险"
            with panel_right:
                yield from self._render_risk(n, m, mp)

    def _render_decision(self, n) -> ComposeResult:
        # Fallback warning
        supporting = getattr(n, "supporting_findings", [])
        invalidation = getattr(n, "invalidation_findings", [])
        why_not = getattr(n, "why_not_now", "") or ""
        has_substance = bool(supporting or invalidation or len(why_not) > 80)
        is_fallback = not has_substance and getattr(n, "confidence", "") == "low"
        if is_fallback:
            yield Static("[yellow]规则估算，按 a 重试[/yellow]", classes="fallback-warn")

        # Action + why
        action_label, _ = ACTION_DISPLAY.get(getattr(n, "action", "PASS"), ("[dim]?[/dim]", "dim"))
        why = getattr(n, "why_now", "") or getattr(n, "why_not_now", "")
        yield Static(f"{action_label}  {why}", classes="panel-row")

        # Verdict
        verdict = getattr(n, "one_line_verdict", "")
        if verdict:
            yield Static(f"[dim]{verdict}[/dim]", classes="panel-row")

        # Confidence
        confidence = getattr(n, "confidence", "low")
        conf_bar = CONFIDENCE_BAR.get(confidence, CONFIDENCE_BAR["low"])
        yield Static(f"置信度 {conf_bar} {confidence}", classes="panel-row")
        yield Static("")

        # Opportunity + execution risk
        opp = getattr(n, "opportunity_type", "")
        risk = getattr(n, "execution_risk", "")
        if opp and opp != "no_trade":
            yield Static(f"{opp} | 风险: {risk}", classes="panel-row")

        # Friction vs edge
        fve = getattr(n, "friction_vs_edge", "")
        fve_map = {"edge_exceeds": "edge > 摩擦", "roughly_equals": "edge ≈ 摩擦", "friction_exceeds": "摩擦 > edge"}
        if fve:
            yield Static(f"摩擦: {fve_map.get(fve, fve)}", classes="panel-row")

        # Time window
        tw = getattr(n, "time_window", None)
        if tw and hasattr(tw, "urgency"):
            label = URGENCY_LABEL.get(tw.urgency, tw.urgency)
            note = tw.note if hasattr(tw, "note") else ""
            yield Static(f"窗口: {label} | {note}", classes="panel-row")

        yield Static("")
        # Next check
        nc = getattr(n, "next_check_at", None)
        nr = getattr(n, "next_check_reason", "")
        if nc:
            yield Static(f"检查: [cyan]{nc[:16]}[/cyan] {nr}", classes="panel-row")

        # Version selector
        if self._versions:
            v = self._versions[self._version_idx]
            total = len(self._versions)
            idx = self._version_idx + 1
            ts = v.created_at[5:16].replace("T", " ")
            yes_p = f"YES {v.yes_price_at_analysis:.2f}" if v.yes_price_at_analysis else ""
            no_p = f"NO {1 - v.yes_price_at_analysis:.2f}" if v.yes_price_at_analysis else ""
            price_note = f"{yes_p} / {no_p}" if yes_p else ""
            trigger_map = {"manual": "手动", "scheduled": "定时", "movement": "异动", "scan": "扫描"}
            trigger_label = trigger_map.get(v.trigger_source, v.trigger_source)
            yield Static(f"[dim]v{v.version} ({ts}) {price_note} [{trigger_label}] < > ({idx}/{total})[/dim]", classes="panel-row")

        # Bias
        bias = getattr(n, "bias", "NONE")
        strength = getattr(n, "strength", "")
        if bias and bias not in ("NONE", "neutral", None):
            bias_cn = {"YES": "偏 YES", "NO": "偏 NO"}.get(str(bias), str(bias))
            yield Static(f"方向: {bias_cn} ({strength})" if strength else f"方向: {bias_cn}", classes="panel-row")

    def _render_risk(self, n, m, mp) -> ComposeResult:
        # Risk calculator
        if m.yes_price and m.yes_price > 0:
            pos = 20.0
            friction_pct = m.round_trip_friction_pct or 0.04
            friction_cost = pos * friction_pct
            profit = (pos / m.yes_price) * 1.0 - pos
            net_profit = profit - friction_cost
            yield Static("$20 投入:", classes="panel-row")
            yield Static(f"  最坏 -${pos:.0f} | 摩擦 -${friction_cost:.2f} ({friction_pct:.1%})", classes="panel-row")
            yield Static(f"  判断对 +${net_profit:.2f}", classes="panel-row")

        # Critical risks
        risk_flags = getattr(n, "risk_flags", [])
        for rf in risk_flags:
            if hasattr(rf, "severity") and rf.severity == "critical":
                yield Static(f"! {rf.text}", classes="risk-critical")

        # Crypto context
        crypto = getattr(n, "crypto", None)
        if crypto and hasattr(crypto, "buffer_conclusion"):
            parts = []
            if crypto.distance_to_threshold_pct is not None:
                parts.append(f"距阈值 {crypto.distance_to_threshold_pct:.1f}%")
            if crypto.buffer_pct is not None:
                parts.append(f"垫 {crypto.buffer_pct:.1f}%")
            if crypto.daily_vol_pct is not None:
                parts.append(f"波动 {crypto.daily_vol_pct:.1f}%")
            parts.append(crypto.buffer_conclusion)
            yield Static(f"Crypto: {' | '.join(parts)}", classes="panel-row")
            if crypto.market_already_knows:
                yield Static(f"[dim]{crypto.market_already_knows}[/dim]", classes="panel-row")

        # Price info
        spread = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
        friction = f"{m.round_trip_friction_pct:.1%}" if m.round_trip_friction_pct else "?"
        bid = f"${m.total_bid_depth_usd:,.0f}" if m.total_bid_depth_usd else "?"
        ask = f"${m.total_ask_depth_usd:,.0f}" if m.total_ask_depth_usd else "?"
        yield Static(f"价差 {spread} | 摩擦 {friction}", classes="panel-row")
        yield Static(f"深度 买{bid} / 卖{ask}", classes="panel-row")

        # Mispricing
        if mp.signal != "none":
            yield Static(f"偏差: {mp.signal.upper()} {mp.details or ''}", classes="panel-row")

    # ===================== EVIDENCE ZONE =====================

    def _compose_evidence_zone(self, n, m) -> ComposeResult:
        with Horizontal(id="evidence-zone"):
            # Left: AI analysis + supporting evidence
            panel_left = DashPanel(id="panel-evidence")
            panel_left.border_title = "AI 分析 + 依据"
            with panel_left:
                yield from self._render_evidence(n, m)

            # Right: Risks + counter-evidence
            panel_right = DashPanel(id="panel-counter")
            panel_right.border_title = "风险 + 反驳"
            with panel_right:
                yield from self._render_counter(n)

    def _render_evidence(self, n, m) -> ComposeResult:
        # Summary
        summary = getattr(n, "summary", "")
        if summary:
            yield Static(summary, classes="panel-row")

        # Counterparty
        cp = getattr(n, "counterparty_note", "")
        if cp:
            yield Static(f"[dim]对手方:[/dim] {cp}", classes="panel-row")

        # Supporting findings
        supporting = getattr(n, "supporting_findings", [])
        if supporting:
            yield Static("[bold]依据[/bold]", classes="section-label")
            for f in supporting:
                if hasattr(f, "finding"):
                    src = f"[dim]{f.source}[/dim]" if f.source else ""
                    yield Static(f"{f.finding} {src}", classes="finding-row")
                    if f.impact:
                        yield Static(f"-> {f.impact}", classes="finding-impact")
                elif isinstance(f, dict):
                    yield Static(f"{f.get('finding', '')} [dim]{f.get('source', '')}[/dim]", classes="finding-row")
                    if f.get("impact"):
                        yield Static(f"-> {f['impact']}", classes="finding-impact")

    def _render_counter(self, n) -> ComposeResult:
        action = getattr(n, "action", "")

        # Why not now
        why_not = getattr(n, "why_not_now", "")
        if why_not and action in ("PASS", "WATCH", "avoid", "watch_only"):
            yield Static(f"[dim]不做的理由:[/dim] {why_not}", classes="panel-row")

        # Recheck conditions
        recheck = getattr(n, "recheck_conditions", [])
        if recheck:
            yield Static("[dim]回看条件:[/dim]", classes="panel-row")
            for cond in recheck[:3]:
                yield Static(f"  - {cond}", classes="panel-row")

        # All risk flags (non-critical)
        risk_flags = getattr(n, "risk_flags", [])
        non_critical = [(rf.text, rf.severity) for rf in risk_flags
                        if hasattr(rf, "severity") and rf.severity != "critical"]
        if non_critical:
            yield Static("[bold]其他风险[/bold]", classes="section-label")
            for text, severity in non_critical:
                yield Static(f"! {text}", classes=f"risk-{severity}")

        # Invalidation findings
        invalidation = getattr(n, "invalidation_findings", [])
        if invalidation:
            yield Static("[bold]可能判断错[/bold]", classes="section-label")
            for f in invalidation:
                if hasattr(f, "finding"):
                    src = f"[dim]{f.source}[/dim]" if f.source else ""
                    yield Static(f"{f.finding} {src}", classes="finding-row")
                    if f.impact:
                        yield Static(f"-> {f.impact}", classes="finding-impact")
                elif isinstance(f, dict):
                    yield Static(f"{f.get('finding', '')} [dim]{f.get('source', '')}[/dim]", classes="finding-row")
                    if f.get("impact"):
                        yield Static(f"-> {f['impact']}", classes="finding-impact")

    # ===================== SCORE BAR =====================

    def _compose_score_bar(self, s) -> ComposeResult:
        if self._show_detail:
            yield from self._compose_score_detail(s)
        else:
            parts = []
            for name, val, mx in [
                ("流动", s.liquidity_structure, 30), ("客观", s.objective_verifiability, 25),
                ("概率", s.probability_space, 20), ("时间", s.time_structure, 15),
                ("摩擦", s.trading_friction, 10),
            ]:
                pct = int(val / mx * 100) if mx > 0 else 0
                parts.append(f"{name}:{pct}%")
            yield Static(f" {' | '.join(parts)} | [bold]总分:{s.total:.0f}[/bold]", id="score-bar")

    def _compose_score_detail(self, s) -> ComposeResult:
        m = self.candidate.market
        import re as _re

        spread = m.spread_pct_yes
        bid = m.total_bid_depth_usd
        liq_parts = []
        if spread is not None:
            liq_parts.append(f"价差 {spread:.1%}")
        if bid is not None:
            liq_parts.append(f"买深 ${bid:,.0f}")
        liq_note = "，".join(liq_parts) if liq_parts else ""

        res_src = m.resolution_source
        if not res_src:
            rules_text = (m.rules or "") + " " + (m.description or "")
            match = _re.search(r"resolution source.*?\bis\b\s+(\w+)", rules_text, _re.IGNORECASE)
            if match:
                res_src = match.group(1)
        obj_note = f"来源: {res_src[:30]}" if res_src else ""

        p = m.yes_price or 0
        prob_note = f"YES {p:.2f}"
        if 0.30 <= p <= 0.70:
            prob_note += " 甜蜜区"

        days = m.days_to_resolution
        time_note = f"{days:.1f}天" if days else ""
        if days and 1.0 <= days <= 5.0:
            time_note += " 最佳窗口"

        friction_pct = m.round_trip_friction_pct
        fric_note = f"来回 {friction_pct:.1%}" if friction_pct else ""

        explanations = {
            "流动性结构": liq_note, "客观验证": obj_note,
            "概率空间": prob_note, "时间结构": time_note, "交易摩擦": fric_note,
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
            yield Static(f" {name:6s} {bar_str} {val:.1f}/{mx}  [dim]{note}[/dim]", classes="panel-row")
        yield Static(f" [bold]总分: {s.total:.0f}/100[/bold]  [dim]按 d 收起[/dim]", classes="panel-row")

    # ===================== ACTIONS =====================

    def action_toggle_detail(self) -> None:
        self.post_message(SwitchVersionRequested(
            self.candidate, self._version_idx, show_detail=not self._show_detail))

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
        if not m.yes_price:
            self.notify("无价格数据", severity="warning")
            return
        price = m.yes_price
        status = "buy_yes" if side == "yes" else "buy_no"

        if self._pending_trade and self._pending_trade == (m.market_id, side):
            from datetime import datetime

            from scanner.market_state import MarketState, get_market_state, set_market_state
            from scanner.paper_trading import mark_paper_trade

            trade_id = mark_paper_trade(
                db=self.service.db, market_id=m.market_id, title=m.title,
                side=side, entry_price=price, market_type=m.market_type,
                structure_score=self.candidate.score.total if self.candidate.score else None,
                mispricing_signal=self.candidate.mispricing.signal,
                scan_id=self.service.last_scan_id,
                position_size_usd=self.service.config.paper_trading.default_position_size_usd,
            )
            state = get_market_state(m.market_id, self.service.db)
            if state is None:
                state = MarketState(status=status, title=m.title)
            state.status = status
            state.updated_at = datetime.now(UTC).isoformat()
            set_market_state(m.market_id, state, self.service.db)
            self.notify(f"Paper trade: {side.upper()} @ {price:.2f} -> {trade_id}")
            self._pending_trade = None
            self.screen.refresh_sidebar_counts()
        else:
            self._pending_trade = (m.market_id, side)
            self.notify(f"再按一次 {side[0]} 确认: {side.upper()} {m.title[:30]} @ {price:.2f}")

    def action_mark_pass(self) -> None:
        from datetime import datetime

        from scanner.market_state import MarketState, get_market_state, set_market_state

        mid = self.candidate.market.market_id
        state = get_market_state(mid, self.service.db)
        if state is None:
            state = MarketState(status="pass", title=self.candidate.market.title)
        state.status = "pass"
        state.updated_at = datetime.now(UTC).isoformat()
        state.auto_monitor = False
        state.next_check_at = None
        state.watch_reason = None
        set_market_state(mid, state, self.service.db)
        from scanner.auto_monitor import cleanup_closed_market
        cleanup_closed_market(mid)
        self.notify(f"PASS: {self.candidate.market.title[:30]}")
        self.screen.refresh_sidebar_counts()

    def action_toggle_auto_monitor(self) -> None:
        from datetime import datetime

        from scanner.auto_monitor import toggle_auto_monitor
        from scanner.market_state import MarketState, get_market_state, set_market_state

        mid = self.candidate.market.market_id
        m = self.candidate.market
        state = get_market_state(mid, self.service.db)

        if state is not None and state.status in ("closed", "pass"):
            self.notify("已关闭或已放弃的市场无法开启监控", severity="warning")
            return

        if state is None:
            n = self._current_narrative()
            state = MarketState(
                status="watch", title=m.title,
                updated_at=datetime.now(UTC).isoformat(),
                price_at_watch=m.yes_price,
                market_type=getattr(m, "market_type", None),
                clob_token_id_yes=getattr(m, "clob_token_id_yes", None),
                condition_id=getattr(m, "condition_id", None),
                resolution_time=m.resolution_time.isoformat() if m.resolution_time else None,
                next_check_at=getattr(n, "next_check_at", None) if n else None,
            )
            set_market_state(mid, state, self.service.db)

        new_value = not state.auto_monitor
        toggle_auto_monitor(mid, enable=new_value, db=self.service.db, config=self.service.config)
        label = "ON" if new_value else "OFF"
        self.notify(f"自动监控 [{label}]: {m.title[:30]}")
        self.screen.refresh_sidebar_counts()

        if new_value:
            try:
                from scanner.watch_scheduler import ensure_daemon_running
                if ensure_daemon_running():
                    self.notify("后台监控已自动启动")
            except Exception:
                pass

    def action_open_link(self) -> None:
        import webbrowser
        try:
            webbrowser.open(self.candidate.market.polymarket_url)
        except Exception:
            self.notify("无法打开浏览器", severity="warning")
