"""MarketDetailView: event detail page with multi-outcome support (v0.5.0).

Data comes entirely from service.get_event_detail(event_id).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalGroup, VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.pnl import calc_unrealized_pnl
from scanner.tui.widgets.cards import DashPanel, MetricCard

if TYPE_CHECKING:
    from scanner.tui.service import ScanService


# ---------------------------------------------------------------------------
# Messages (names preserved for MainScreen compatibility)
# ---------------------------------------------------------------------------


class BackToList(Message):
    pass


class AnalyzeRequested(Message):
    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class CancelAnalysisRequested(Message):
    pass


class SwitchVersionRequested(Message):
    def __init__(self, event_id: str, version_idx: int):
        super().__init__()
        self.event_id = event_id
        self.version_idx = version_idx


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

ACTION_DISPLAY = {
    "PASS": ("[red]PASS[/red]", "red"),
    "WATCH": ("[yellow]WATCH[/yellow]", "yellow"),
    "BUY_YES": ("[green]BUY YES[/green]", "green"),
    "BUY_NO": ("[green]BUY NO[/green]", "green"),
    "HOLD": ("[cyan]HOLD[/cyan]", "cyan"),
    "SELL_YES": ("[red]SELL YES[/red]", "red"),
    "SELL_NO": ("[red]SELL NO[/red]", "red"),
    "REDUCE_YES": ("[yellow]REDUCE YES[/yellow]", "yellow"),
    "REDUCE_NO": ("[yellow]REDUCE NO[/yellow]", "yellow"),
}

CONFIDENCE_BAR = {
    "low": "[red]██[/red][dim]██████[/dim]",
    "medium": "[yellow]█████[/yellow][dim]███[/dim]",
    "high": "[green]███████[/green][dim]█[/dim]",
}


# ---------------------------------------------------------------------------
# MarketDetailView
# ---------------------------------------------------------------------------


class MarketDetailView(Widget):
    """Event detail dashboard.  Constructor takes event_id + service."""

    BINDINGS = [
        Binding("escape", "go_back", "返回"),
        Binding("backspace", "go_back", show=False),
        Binding("a", "analyze", "AI分析"),
        Binding("p", "mark_pass", "PASS"),
        Binding("m", "toggle_monitor", "监控"),
        Binding("t", "trade", "交易"),
        Binding("v", "switch_version", "版本"),
        Binding("o", "open_link", "链接"),
    ]

    DEFAULT_CSS = """
    MarketDetailView { height: 1fr; }
    MarketDetailView .hdr-title { text-style: bold; color: $primary; padding: 1 0 0 1; }
    MarketDetailView .hdr-sub { color: $text-muted; padding: 0 0 0 2; }
    MarketDetailView .section-label { text-style: bold; color: $primary; padding: 1 0 0 1; }
    MarketDetailView .row { padding: 0 0 0 1; }
    MarketDetailView .muted { color: $text-muted; padding: 0 0 0 1; }
    MarketDetailView .risk-critical { color: $error; padding: 0 0 0 1; }
    MarketDetailView .risk-warning { color: $warning; padding: 0 0 0 1; }
    MarketDetailView .risk-info { color: $text-muted; padding: 0 0 0 1; }

    MarketDetailView #kpi-row {
        height: auto; min-height: 5; padding: 0;
    }
    MarketDetailView #kpi-row MetricCard {
        height: 5; margin: 0 1;
    }
    MarketDetailView #panels {
        height: auto; min-height: 10;
    }
    MarketDetailView #panels DashPanel {
        width: 1fr; margin: 0 1; height: auto;
    }
    MarketDetailView #sub-markets {
        height: auto; max-height: 14; margin: 0 1;
    }
    MarketDetailView #footer-hint {
        height: 1; color: $text-muted; padding: 0 1;
    }
    """

    def __init__(
        self,
        event_id: str,
        service: ScanService,
        *,
        analyzing: bool = False,
        version_idx: int | None = None,
    ):
        super().__init__()
        self.event_id = event_id
        self.service = service
        self._analyzing = analyzing
        self._requested_version_idx = version_idx

        # Load data synchronously so compose() has it
        self._detail = self.service.get_event_detail(self.event_id)
        self._version_idx: int = -1
        self._expanded_markets: set[str] = set()  # market_ids with expanded score breakdown
        self._sub_row_map: list[dict] = []  # maps sub-market table rows

        if self._detail is not None:
            analyses = self._detail.get("analyses", [])
            if analyses:
                if (
                    self._requested_version_idx is not None
                    and 0 <= self._requested_version_idx < len(analyses)
                ):
                    self._version_idx = self._requested_version_idx
                else:
                    self._version_idx = len(analyses) - 1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._populate()

    def _populate(self) -> None:
        """Fill all widgets with data after mount + load."""
        d = self._detail
        if d is None:
            return
        self._fill_kpi()

        # Fill sub-market table for multi-outcome events
        markets = d.get("markets", [])
        if len(markets) > 1:
            self._rebuild_sub_market_table(markets)

    def _rebuild_sub_market_table(self, markets: list) -> None:
        """Build sub-market table with expandable score breakdown."""
        try:
            table = self.query_one("#sub-market-table", DataTable)
        except Exception:
            return

        table.clear()
        self._sub_row_map = []

        from scanner.tui.utils import format_countdown

        for mr in markets:
            label = mr.group_item_title or mr.question[:40]
            # 结算列已显示"(已过期)"，标题不再重复标注
            is_expanded = mr.market_id in self._expanded_markets
            prefix = "▼ " if is_expanded else "▶ " if not mr.closed else "  "

            yes = f"{mr.yes_price:.2f}" if mr.yes_price is not None else "?"
            no = f"{mr.no_price:.2f}" if mr.no_price is not None else "?"
            spread = f"{mr.spread:.1%}" if mr.spread else "?"
            vol = f"${mr.volume:,.0f}" if mr.volume else "?"
            end = format_countdown(mr.end_date) if mr.end_date else "?"

            table.add_row(f"{prefix}{label}", yes, no, spread, vol, end, key=f"m_{mr.market_id}")
            self._sub_row_map.append({"type": "market", "market": mr})

            if is_expanded:
                self._add_score_breakdown_rows(table, mr)

    def _add_score_breakdown_rows(self, table: DataTable, mr) -> None:
        """Insert score breakdown rows from stored data (or compute on-demand)."""
        import json as _json

        total = mr.structure_score or 0

        # Read stored breakdown if available
        import contextlib
        bd = None
        if mr.score_breakdown:
            with contextlib.suppress(ValueError, TypeError):
                bd = _json.loads(mr.score_breakdown)

        # Get type-specific max weights
        from scanner.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS
        mtype = getattr(mr, "market_type", None) or "other"
        # Try to get market_type from parent event if not on market
        if mtype == "other" and self._detail:
            ev = self._detail.get("event")
            if ev:
                mtype = getattr(ev, "market_type", None) or "other"
        tw = _TYPE_WEIGHTS.get(mtype, _DEFAULT_WEIGHTS)

        if bd:
            breakdown = [
                ("流动性", bd.get("liquidity", 0), tw["liquidity"]),
                ("可验证性", bd.get("verifiability", 0), tw["verifiability"]),
                ("概率空间", bd.get("probability", 0), tw["probability"]),
                ("时间", bd.get("time", 0), tw["time"]),
                ("摩擦", bd.get("friction", 0), tw["friction"]),
            ]
            if tw.get("net_edge", 0) > 0:
                breakdown.append(("Edge", bd.get("net_edge", 0), tw["net_edge"]))
        else:
            breakdown = []

        # Dimension key mapping for commentary lookup
        dim_keys = ["liquidity", "verifiability", "probability", "time", "friction"]
        if tw.get("net_edge", 0) > 0:
            dim_keys.append("net_edge")

        from rich.text import Text
        for i, (name, val, max_val) in enumerate(breakdown):
            # Cap to current weight (breakdown may be from older scan with different weights)
            val = min(val, max_val) if max_val > 0 else val
            bar_len = int(val / max_val * 15) if max_val > 0 else 0
            bar = "█" * bar_len + "░" * (15 - bar_len)
            comment = ""
            if i < len(dim_keys):
                comment = bd.get("commentary", {}).get("dim_comments", {}).get(dim_keys[i], "")
            label = f"  ├ {name}"
            table.add_row(
                label, f"{bar} {val:.0f}/{max_val}", comment, "", "", "",
                key=f"bd_{mr.market_id}_{i}",
            )
            self._sub_row_map.append({"type": "breakdown", "market_id": mr.market_id})

        # Total score + overall commentary on the same row
        total_bar_len = int(total / 100 * 15)
        total_bar = "█" * total_bar_len + "░" * (15 - total_bar_len)
        overall_comment = bd.get("commentary", {}).get("overall", "")
        table.add_row(
            "  └ 总分", f"{total_bar} {total:.0f}/100", overall_comment, "", "", "",
            key=f"bd_{mr.market_id}_total",
        )
        self._sub_row_map.append({"type": "breakdown", "market_id": mr.market_id})

    def _on_sub_market_selected(self, row_idx: int) -> None:
        """Handle Enter/click on sub-market table row."""
        if row_idx < 0 or row_idx >= len(self._sub_row_map):
            return
        item = self._sub_row_map[row_idx]
        if item["type"] == "market":
            mr = item["market"]
            if mr.closed:
                return  # don't expand expired
            mid = mr.market_id
            if mid in self._expanded_markets:
                self._expanded_markets.discard(mid)
            else:
                self._expanded_markets.add(mid)
            markets = (self._detail or {}).get("markets", [])
            self._rebuild_sub_market_table(markets)

    # ------------------------------------------------------------------
    # Compose
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        d = self._detail or {}
        event = d.get("event")
        markets = d.get("markets", [])
        analyses = d.get("analyses", [])
        is_multi = len(markets) > 1

        with VerticalScroll():
            # --- Header ---
            title = event.title if event else self.event_id
            yield Static(f"[bold]{title}[/bold]", classes="hdr-title")

            monitor = d.get("monitor")
            monitor_str = (
                "[green]监控 ON[/green]"
                if monitor and monitor.get("auto_monitor")
                else "[dim]监控 OFF[/dim]"
            )
            deadline_str = "?"
            if event and event.end_date:
                from scanner.tui.utils import format_countdown
                deadline_str = format_countdown(event.end_date)
            mtype = (event.market_type or "other") if event else "?"
            yield Static(
                f"{mtype} | 结算: {deadline_str} | {monitor_str}",
                classes="hdr-sub",
            )

            # --- KPI Row ---
            with HorizontalGroup(id="kpi-row"):
                if is_multi:
                    leader_label = self._leader_card_label(event, markets)
                    yield self._make_card("kpi-leader", leader_label)
                    if event.neg_risk:
                        yield self._make_card("kpi-overround", "溢价率")
                    else:
                        yield self._make_card("kpi-overround", "最小价差")
                    yield self._make_card("kpi-count", "子市场")
                    yield self._make_card("kpi-end", "结算")
                    yield self._make_card("kpi-score", "评分")
                else:
                    yield self._make_card("kpi-yes", "YES")
                    yield self._make_card("kpi-no", "NO")
                    yield self._make_card("kpi-spread", "价差")
                    yield self._make_card("kpi-score", "评分")

            # --- Sub-market table (multi-outcome only) ---
            if is_multi:
                yield Static("")
                table = DataTable(id="sub-market-table")
                table.cursor_type = "row"
                table.add_columns("选项", "YES", "NO", "价差", "成交量", "结算")
                yield table

            # --- Analyzing state ---
            # --- Position panel (always on top) ---
            yield from self._compose_position_panel(d)

            # --- AI Analysis panel (below) ---
            if self._analyzing:
                yield Static("AI 分析中...", classes="section-label")
                yield Static("正在联网搜索 + 分析，请稍候...", classes="row")
            elif analyses:
                yield Static("")
                yield from self._compose_analysis_panel(analyses)
            else:
                yield Static("")
                yield Static("[dim]按 a 启动 AI 分析[/dim]", classes="row")

            # --- Footer ---
            yield Static("")
            yield Static(
                "[dim]Esc 返回 | a 分析 | p PASS | m 监控 | t 交易 | v 版本 | o 链接[/dim]",
                id="footer-hint",
            )

    @staticmethod
    def _make_card(card_id: str, title: str) -> MetricCard:
        card = MetricCard(id=card_id)
        card.border_title = title
        return card

    # ------------------------------------------------------------------
    # KPI cards
    # ------------------------------------------------------------------

    def _fill_kpi(self) -> None:
        d = self._detail
        if d is None:
            return
        event = d["event"]
        markets = d.get("markets", [])

        if len(markets) > 1:
            self._fill_kpi_multi(event, markets)
        else:
            self._fill_kpi_binary(event, markets)

    def _fill_kpi_binary(self, event, markets) -> None:
        """Fill KPI cards for a single (binary) market."""
        mr = markets[0] if markets else None
        yes = mr.yes_price if mr and mr.yes_price is not None else 0
        no = mr.no_price if mr and mr.no_price is not None else round(1 - yes, 4)
        spread = mr.spread if mr and mr.spread else None

        self._set_card("kpi-yes", f"{yes:.3f}")
        self._set_card("kpi-no", f"{no:.3f}")
        spread_str = f"{spread:.1%}" if spread else "?"
        self._set_card("kpi-spread", spread_str)

        score = event.structure_score
        mkt_summary = self._market_score_summary(markets)
        score_text = f"事件 {score:.0f}" if score else "?"
        if mkt_summary:
            score_text += f"\n{mkt_summary}"
        self._set_card("kpi-score", score_text)

    def _market_score_summary(self, markets) -> str:
        """Summarize sub-market scores: avg (min~max)."""
        scores = [m.structure_score for m in markets if m.structure_score is not None and not m.closed]
        if not scores:
            return ""
        avg = sum(scores) / len(scores)
        return f"市场 {avg:.0f} ({min(scores):.0f}~{max(scores):.0f})"



    def _fill_kpi_multi(self, event, markets) -> None:
        """Fill KPI cards for multi-outcome events."""
        active = [m for m in markets if not m.closed and m.yes_price is not None]
        if event.neg_risk:
            self._fill_leader_neg_risk(active)
        else:
            self._fill_leader_independent(active)

        # negRisk: overround | non-negRisk: tightest spread
        if event.neg_risk:
            prices = [m.yes_price for m in active if m.yes_price is not None]
            if prices:
                overround = sum(prices) - 1.0
                total_spread = sum(m.spread for m in active if m.spread is not None)
                net = overround + total_spread
                sign = "+" if overround >= 0 else ""
                net_sign = "+" if net >= 0 else ""
                self._set_card("kpi-overround", f"{sign}{overround:.1%}\n净{net_sign}{net:.1%}")
            else:
                self._set_card("kpi-overround", "?")
        else:
            spreads = [
                m.spread for m in active
                if m.spread is not None and m.spread > 0
                and m.yes_price is not None and 0.05 <= m.yes_price <= 0.95
            ]
            if spreads:
                best = min(spreads)
                self._set_card("kpi-overround", f"{best:.1%}")
            else:
                self._set_card("kpi-overround", "?")

        closed_count = sum(1 for m in markets if m.closed)
        count_str = str(len(markets))
        if closed_count > 0:
            count_str += f" ({closed_count}过期)"
        self._set_card("kpi-count", count_str)

        # Date range for active sub-markets
        from datetime import UTC, datetime

        from scanner.tui.utils import format_countdown_range
        now_iso = datetime.now(UTC).isoformat()
        active_ends = [m.end_date for m in markets if not m.closed and m.end_date and m.end_date > now_iso]
        if active_ends:
            self._set_card("kpi-end", format_countdown_range(min(active_ends), max(active_ends)))
        else:
            self._set_card("kpi-end", "?")

        score = event.structure_score
        mkt_summary = self._market_score_summary(markets)
        score_text = f"事件 {score:.0f}" if score else "?"
        if mkt_summary:
            score_text += f"\n{mkt_summary}"
        self._set_card("kpi-score", score_text)

    @staticmethod
    def _leader_card_label(event, markets) -> str:
        """Choose card title based on event type."""
        import re
        if event.neg_risk:
            return "领先"
        title = event.title or ""
        # Threshold: "above/below ___"
        if re.search(r'\b(above|below|exceed|reach)\b', title, re.I):
            return "关注区"
        # Deadline: "by...?" / "ends by"
        if re.search(r'\bby\b', title, re.I) or re.search(r'ends?\s+by', title, re.I):
            return "最近窗口"
        return "最高概率"

    def _fill_leader_neg_risk(self, active) -> None:
        """negRisk: show the option with highest YES price."""
        leader = max(active, key=lambda m: m.yes_price or 0, default=None)
        if leader and leader.yes_price is not None:
            name = (leader.group_item_title or leader.question)[:20]
            no = leader.no_price if leader.no_price is not None else round(1 - leader.yes_price, 4)
            self._set_card("kpi-leader", f"{name}\nYES:{leader.yes_price:.2f} NO:{no:.2f}")
        else:
            self._set_card("kpi-leader", "?")

    def _fill_leader_independent(self, active) -> None:
        """Non-negRisk: show ATM zone or nearest meaningful deadline."""
        # Find markets with YES closest to 0.50 (most uncertain = most interesting)
        tradeable = [m for m in active if m.yes_price and 0.05 <= m.yes_price <= 0.95]
        if tradeable:
            # Sort by distance from 0.50
            tradeable.sort(key=lambda m: abs(m.yes_price - 0.5))
            best = tradeable[0]
            name = (best.group_item_title or best.question)[:20]
            self._set_card("kpi-leader", f"{name}\nYES:{best.yes_price:.2f} NO:{best.no_price:.2f}")
        else:
            self._set_card("kpi-leader", "无可交易标的")

    def _set_card(self, card_id: str, content: str) -> None:
        import contextlib
        with contextlib.suppress(Exception):
            self.query_one(f"#{card_id}", MetricCard).update(content)

    # ------------------------------------------------------------------
    # Analysis panel (left)
    # ------------------------------------------------------------------

    def _compose_analysis_panel(self, analyses) -> ComposeResult:
        panel = DashPanel(id="panel-analysis")
        panel.border_title = "AI 分析"
        with panel:
            n = self._current_narrative(analyses)
            if n is None:
                yield Static("[dim]无分析数据[/dim]", classes="row")
                return

            # --- KPI Row ---
            mode = n.get("mode", "discovery")
            action = n.get("action", "PASS")
            action_label, _ = ACTION_DISPLAY.get(action, ("[dim]?[/dim]", "dim"))

            # "判定" card: action + direction (discovery) or action + thesis_status (position)
            if mode == "position_management":
                ts = n.get("thesis_status", "")
                ts_label = {"intact": "论点完整", "weakened": "论点减弱", "broken": "论点失效"}.get(ts, "")
                action_content = f"{action_label}\n{ts_label}" if ts_label else action_label
            else:
                action_content = action_label

            # "置信度" card: just confidence bar
            confidence = n.get("confidence", "low")
            conf_bar = CONFIDENCE_BAR.get(confidence, CONFIDENCE_BAR["low"])
            conf_label = {"low": "低", "medium": "中", "high": "高"}.get(confidence, confidence)
            conf_content = f"{conf_bar} {conf_label}"

            # "时间窗口" card: keep as-is
            tw = n.get("time_window", {})
            if isinstance(tw, dict):
                urgency = tw.get("urgency", "")
                optimal = tw.get("optimal_entry")
            else:
                urgency = ""
                optimal = None
            urgency_label = {"urgent": "紧急", "normal": "正常", "no_rush": "不急"}.get(urgency, urgency)
            if optimal:
                # Show optimal entry time in local timezone
                from datetime import datetime, timezone
                try:
                    opt_dt = datetime.fromisoformat(optimal)
                    opt_local = opt_dt.astimezone().strftime("%m-%d %H:%M")
                    time_content = f"{urgency_label}\n最佳入场 {opt_local}"
                except (ValueError, TypeError):
                    time_content = urgency_label
            else:
                time_content = urgency_label

            # "摩擦vs边际" card: friction_vs_edge (discovery) or stop_loss/take_profit (position)
            if mode == "position_management":
                sl = n.get("stop_loss")
                tp = n.get("take_profit")
                parts = []
                if sl is not None:
                    parts.append(f"止损 {sl:.2f}")
                if tp is not None:
                    parts.append(f"止盈 {tp:.2f}")
                fve_content = "\n".join(parts) if parts else "[dim]无[/dim]"
            else:
                fve = n.get("friction_vs_edge", "")
                fve_content = {"edge_exceeds": "edge > 摩擦", "roughly_equals": "edge ≈ 摩擦", "friction_exceeds": "摩擦 > edge"}.get(fve, fve)

            def _card(content, card_id, title):
                c = MetricCard(content, id=card_id)
                c.border_title = title
                return c

            with HorizontalGroup(id="ai-kpi-row1"):
                yield _card(action_content, "ai-action", "判定")
                yield _card(conf_content, "ai-conf", "置信度")
            with HorizontalGroup(id="ai-kpi-row2"):
                yield _card(time_content, "ai-time", "时间窗口")
                yield _card(fve_content, "ai-fve", "摩擦vs边际")

            # --- Verdict ---
            verdict = n.get("one_line_verdict", "")
            if verdict:
                yield Static(f"\n[bold]{verdict}[/bold]", classes="row")

            # --- Two sub-panels ---
            with Horizontal(id="ai-panels"):
                yield from self._compose_ai_why_panel(n)
                yield from self._compose_ai_evidence_panel(n)

            # --- Next check + version ---
            nc = n.get("next_check_at")
            nr = n.get("next_check_reason", "")
            nc_str = f"下次检查: [cyan]{nc[:16]}[/cyan] {nr}" if nc else ""
            yield Static("")
            yield from self._compose_version_selector(analyses, extra=nc_str)

    def _compose_ai_why_panel(self, n: dict) -> ComposeResult:
        """Left sub-panel: why/why not + risks + recheck + position thesis."""
        mode = n.get("mode", "discovery")
        panel = DashPanel(id="ai-why")
        panel.border_title = "决策依据"
        with panel:
            # Time window note (full text)
            tw = n.get("time_window", {})
            tw_note = tw.get("note", "") if isinstance(tw, dict) else ""
            if tw_note:
                yield Static(f"[cyan]时间:[/cyan] {tw_note}", classes="row")

            # Why / why not (new schema uses "why" and "why_not")
            why = n.get("why") or n.get("why_now") or ""
            why_not = n.get("why_not") or n.get("why_not_now") or ""
            if why:
                yield Static(f"[green]为什么:[/green] {why}", classes="row")
            if why_not:
                yield Static(f"[yellow]为什么不:[/yellow] {why_not}", classes="row")

            # Position mode: thesis status
            if mode == "position_management":
                ts = n.get("thesis_status", "")
                tn = n.get("thesis_note", "")
                ts_icon = {"intact": "[green]✓[/green]", "weakened": "[yellow]~[/yellow]", "broken": "[red]✗[/red]"}.get(ts, "?")
                if ts:
                    yield Static(f"\n[bold]论点状态[/bold] {ts_icon} {ts}", classes="row")
                if tn:
                    yield Static(f"  {tn}", classes="row")
                pnl_note = n.get("current_pnl_note", "")
                if pnl_note:
                    yield Static(f"  {pnl_note}", classes="row")
                sl = n.get("stop_loss")
                tp = n.get("take_profit")
                if sl is not None or tp is not None:
                    sl_str = f"止损 {sl:.2f}" if sl is not None else ""
                    tp_str = f"止盈 {tp:.2f}" if tp is not None else ""
                    yield Static(f"  {sl_str}  {tp_str}".strip(), classes="row")

            # Discovery mode: recommended market + entry (only for BUY actions)
            action = n.get("action", "PASS")
            if mode == "discovery" and action in ("BUY_YES", "BUY_NO"):
                rec = n.get("recommended_market_title") or n.get("recommended_market_id")
                direction = n.get("direction")
                entry = n.get("entry_price")
                size = n.get("position_size_usd")
                if rec:
                    parts = [f"[bold]推荐:[/bold] {rec}"]
                    if entry:
                        parts.append(f"限价 {entry:.2f}")
                    if size:
                        parts.append(f"仓位 ${size:.0f}")
                    yield Static(f"\n{'  '.join(parts)}", classes="row")

                overview = n.get("event_overview", "")
                if overview:
                    yield Static(f"[dim]{overview}[/dim]", classes="row")

            # Summary
            summary = n.get("summary", "")
            if summary:
                yield Static(f"\n{summary}", classes="row")

            # Risk flags (all severities)
            risks = n.get("risk_flags", [])
            if risks:
                yield Static("\n[bold]风险[/bold]", classes="row")
                for rf in risks:
                    sev = rf.get("severity", "info") if isinstance(rf, dict) else "info"
                    text = rf.get("text", str(rf)) if isinstance(rf, dict) else str(rf)
                    icon = {"critical": "[red]![/red]", "warning": "[yellow]⚠[/yellow]", "info": "[dim]ℹ[/dim]"}.get(sev, "·")
                    yield Static(f"  {icon} {text}", classes="row")

            # Recheck conditions
            conditions = n.get("recheck_conditions", [])
            if conditions:
                yield Static("\n[bold]重新关注条件[/bold]", classes="row")
                for c in conditions:
                    yield Static(f"  · {c}", classes="row")

    def _compose_ai_evidence_panel(self, n: dict) -> ComposeResult:
        """Right sub-panel: supporting + invalidation findings + crypto context."""
        panel = DashPanel(id="ai-evidence")
        panel.border_title = "AI 调研发现"
        with panel:
            # Supporting findings
            supporting = n.get("supporting_findings", [])
            if supporting:
                yield Static("[green]支撑证据[/green]", classes="row")
                for f in supporting:
                    if isinstance(f, dict):
                        finding = f.get("finding", "")
                        source = f.get("source", "")
                        impact = f.get("impact", "")
                        yield Static(f"  ✓ {finding}", classes="row")
                        if source or impact:
                            yield Static(f"    [dim]{source} → {impact}[/dim]", classes="row")
                    else:
                        yield Static(f"  ✓ {f}", classes="row")

            # Invalidation findings
            invalid = n.get("invalidation_findings", [])
            if invalid:
                yield Static(f"\n[red]失效条件[/red]", classes="row")
                for f in invalid:
                    if isinstance(f, dict):
                        finding = f.get("finding", "")
                        source = f.get("source", "")
                        impact = f.get("impact", "")
                        yield Static(f"  ✗ {finding}", classes="row")
                        if source or impact:
                            yield Static(f"    [dim]{source} → {impact}[/dim]", classes="row")
                    else:
                        yield Static(f"  ✗ {f}", classes="row")

            # Crypto context
            crypto = n.get("crypto")
            if crypto and isinstance(crypto, dict):
                yield Static(f"\n[bold]Crypto[/bold]", classes="row")
                dist = crypto.get("distance_to_threshold_pct")
                buf = crypto.get("buffer_conclusion", "")
                vol = crypto.get("daily_vol_pct")
                parts = []
                if dist is not None:
                    parts.append(f"距阈值 {dist:.1f}%")
                if buf:
                    parts.append(f"缓冲 {buf}")
                if vol is not None:
                    parts.append(f"日波动 {vol:.1f}%")
                if parts:
                    yield Static(f"  {' | '.join(parts)}", classes="row")
                mak = crypto.get("market_already_knows", "")
                if mak:
                    yield Static(f"  [dim]{mak}[/dim]", classes="row")

            # Alternative market (position mode: swap recommendation)
            alt_id = n.get("alternative_market_id")
            alt_note = n.get("alternative_note", "")
            if alt_id:
                yield Static(f"\n[bold]换仓建议[/bold]", classes="row")
                yield Static(f"  → {alt_id} {alt_note}", classes="row")

            # Counterparty note
            cn = n.get("counterparty_note", "")
            if cn:
                yield Static(f"\n[dim]{cn}[/dim]", classes="row")

            # If no evidence at all
            if not supporting and not invalid and not crypto and not alt_id:
                yield Static("[dim]无调研数据[/dim]", classes="row")

    def _compose_version_selector(self, analyses, extra: str = "") -> ComposeResult:
        if not analyses or self._version_idx < 0:
            return
        v = analyses[self._version_idx]
        total = len(analyses)
        idx = self._version_idx + 1
        # Convert UTC to local time for display
        from datetime import datetime, timezone
        try:
            utc_dt = datetime.fromisoformat(v.created_at)
            local_dt = utc_dt.astimezone()
            ts = local_dt.strftime("%m-%d %H:%M")
        except (ValueError, TypeError):
            ts = v.created_at[5:16].replace("T", " ")

        trigger_map = {
            "manual": "手动", "scheduled": "定时",
            "movement": "异动", "scan": "扫描",
        }
        trigger_label = trigger_map.get(v.trigger_source, v.trigger_source)
        parts = [f"v{v.version} ({ts}) [{trigger_label}] ({idx}/{total}) 按v切换"]
        if extra:
            parts.append(extra)
        yield Static(f"[dim]{' | '.join(parts)}[/dim]", classes="row")

    def _current_narrative(self, analyses) -> dict | None:
        """Get the narrative_output dict from the selected version."""
        if not analyses or self._version_idx < 0:
            return None
        v = analyses[self._version_idx]
        return v.narrative_output if v.narrative_output else None

    # ------------------------------------------------------------------
    # Position panel (right)
    # ------------------------------------------------------------------

    def _compose_position_panel(self, d: dict) -> ComposeResult:
        panel = DashPanel(id="panel-position")
        panel.border_title = "持仓"
        with panel:
            trades = d.get("trades", [])
            if not trades:
                yield Static("[dim]无持仓[/dim]", classes="row")
                return

            for t in trades:
                side = t.get("side", "?").upper()
                entry = t.get("entry_price", 0)
                size = t.get("position_size_usd", 0)
                title = (t.get("title") or "")[:30]
                yield Static(
                    f"{side} @ {entry:.2f}  ${size:.0f}  {title}",
                    classes="row",
                )

                # Unrealized P&L estimate (if market still has price)
                markets = d.get("markets", [])
                mid = t.get("market_id", "")
                current_mr = next(
                    (m for m in markets if m.market_id == mid), None,
                )
                if current_mr and current_mr.yes_price is not None and entry > 0:
                    pnl_data = calc_unrealized_pnl(
                        side.lower(), entry, current_mr.yes_price, size,
                    )
                    unrealized = pnl_data["pnl"]
                    color = "green" if unrealized >= 0 else "red"
                    yield Static(
                        f"  [{color}]P&L: {unrealized:+.2f}[/{color}]",
                        classes="row",
                    )

            # Movement log summary
            movements = d.get("movements", [])
            if movements:
                yield Static("")
                latest = movements[0]
                mag = latest.get("magnitude", 0)
                qual = latest.get("quality", 0)
                label = latest.get("label", "")
                yield Static(
                    f"[dim]最近异动: M={mag:.0f} Q={qual:.0f} {label}[/dim]",
                    classes="row",
                )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_go_back(self) -> None:
        if self._analyzing:
            self.post_message(CancelAnalysisRequested())
        else:
            self.post_message(BackToList())

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter/click on sub-market table — toggle score breakdown."""
        if event.data_table.id == "sub-market-table":
            self._on_sub_market_selected(event.cursor_row)

    def action_analyze(self) -> None:
        if self._analyzing:
            return
        self._analyzing = True
        self.post_message(AnalyzeRequested(self.event_id))

    def action_mark_pass(self) -> None:
        self.service.pass_event(self.event_id)
        event = self._detail["event"] if self._detail else None
        title = (event.title[:30] if event else self.event_id)
        self.notify(f"PASS: {title}")
        self.screen.refresh_sidebar_counts()

    def action_toggle_monitor(self) -> None:
        monitor = (
            self._detail.get("monitor") if self._detail else None
        )
        currently_on = bool(monitor and monitor.get("auto_monitor"))
        self.service.toggle_monitor(self.event_id, enable=not currently_on)
        state = "OFF" if currently_on else "ON"
        self.notify(f"监控 {state}")
        self.screen.refresh_sidebar_counts()
        # Rebuild view to reflect new state
        self.post_message(
            SwitchVersionRequested(self.event_id, self._version_idx)
        )

    def action_trade(self) -> None:
        self.notify("交易功能开发中")

    def action_switch_version(self) -> None:
        analyses = (
            self._detail.get("analyses", []) if self._detail else []
        )
        if not analyses:
            self.notify("无分析版本")
            return
        # Cycle to next version (wrap around)
        next_idx = (self._version_idx + 1) % len(analyses)
        self.post_message(
            SwitchVersionRequested(self.event_id, next_idx)
        )

    def action_open_link(self) -> None:
        event = self._detail.get("event") if self._detail else None
        if event and event.slug:
            import webbrowser
            url = f"https://polymarket.com/event/{event.slug}"
            try:
                webbrowser.open(url)
            except Exception:
                self.notify("无法打开浏览器", severity="warning")
        else:
            self.notify("无链接信息", severity="warning")
