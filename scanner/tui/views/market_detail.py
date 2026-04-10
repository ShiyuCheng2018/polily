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
    "SELL": ("[red]SELL[/red]", "red"),
    "REDUCE": ("[yellow]REDUCE[/yellow]", "yellow"),
}

CONFIDENCE_BAR = {
    "low": "[dim]|||||.....[/dim]",
    "medium": "[yellow]|||||||...[/yellow]",
    "high": "[green]|||||||||.[/green]",
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

        # Populated in on_mount
        self._detail: dict | None = None
        self._version_idx: int = -1

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._load_data()

    def _load_data(self) -> None:
        """Load event detail from service and populate the view."""
        self._detail = self.service.get_event_detail(self.event_id)
        if self._detail is None:
            return

        analyses = self._detail.get("analyses", [])
        if analyses:
            if (
                self._requested_version_idx is not None
                and 0 <= self._requested_version_idx < len(analyses)
            ):
                self._version_idx = self._requested_version_idx
            else:
                self._version_idx = len(analyses) - 1
        else:
            self._version_idx = -1

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
            try:
                table = self.query_one("#sub-market-table", DataTable)
                table.clear()
                for mr in markets:
                    label = mr.group_item_title or mr.question[:40]
                    yes = f"{mr.yes_price:.2f}" if mr.yes_price is not None else "?"
                    no = f"{mr.no_price:.2f}" if mr.no_price is not None else "?"
                    spread = f"{mr.spread:.1%}" if mr.spread else "?"
                    vol = f"${mr.volume:,.0f}" if mr.volume else "?"
                    table.add_row(label, yes, no, spread, vol, key=mr.market_id)
            except Exception:
                pass

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
                    yield self._make_card("kpi-leader", "领先")
                    yield self._make_card("kpi-entropy", "分散度")
                    yield self._make_card("kpi-count", "子市场")
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
                table.add_columns("选项", "YES", "NO", "价差", "成交量")
                yield table

            # --- Analyzing state ---
            if self._analyzing:
                yield Static("AI 分析中...", classes="section-label")
                yield Static("正在联网搜索 + 分析，请稍候...", classes="row")
            elif analyses:
                yield Static("")
                # --- Two-column panels ---
                with Horizontal(id="panels"):
                    yield from self._compose_analysis_panel(analyses)
                    yield from self._compose_position_panel(d)
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
        self._set_card("kpi-score", f"{score:.0f}" if score else "?")

    def _fill_kpi_multi(self, event, markets) -> None:
        """Fill KPI cards for multi-outcome (negRisk) events."""
        # Leader: highest yes_price
        leader = max(markets, key=lambda m: m.yes_price or 0, default=None)
        if leader and leader.yes_price is not None:
            name = (leader.group_item_title or leader.question)[:20]
            self._set_card("kpi-leader", f"{name}\n{leader.yes_price:.2f}")
        else:
            self._set_card("kpi-leader", "?")

        # Entropy (measure of probability dispersion)
        prices = [m.yes_price for m in markets if m.yes_price and m.yes_price > 0]
        if prices:
            total = sum(prices)
            norm = [p / total for p in prices] if total > 0 else prices
            entropy = -sum(p * math.log2(p) for p in norm if p > 0)
            max_entropy = math.log2(len(prices)) if len(prices) > 1 else 1
            rel_entropy = entropy / max_entropy if max_entropy > 0 else 0
            self._set_card("kpi-entropy", f"{rel_entropy:.2f}")
        else:
            self._set_card("kpi-entropy", "?")

        self._set_card("kpi-count", str(len(markets)))

        score = event.structure_score
        self._set_card("kpi-score", f"{score:.0f}" if score else "?")

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

            # Action + why
            action = n.get("action", "PASS")
            action_label, _ = ACTION_DISPLAY.get(action, ("[dim]?[/dim]", "dim"))
            why = n.get("why_now") or n.get("why_not_now", "")
            yield Static(f"{action_label}  {why}", classes="row")

            # Verdict
            verdict = n.get("one_line_verdict", "")
            if verdict:
                yield Static(f"[dim]{verdict}[/dim]", classes="row")

            # Confidence
            confidence = n.get("confidence", "low")
            bar = CONFIDENCE_BAR.get(confidence, CONFIDENCE_BAR["low"])
            yield Static(f"置信度 {bar} {confidence}", classes="row")

            # Summary
            summary = n.get("summary", "")
            if summary:
                yield Static("")
                yield Static(summary, classes="row")

            # Risk flags (critical)
            for rf in n.get("risk_flags", []):
                sev = rf.get("severity", "info") if isinstance(rf, dict) else "info"
                text = rf.get("text", str(rf)) if isinstance(rf, dict) else str(rf)
                if sev == "critical":
                    yield Static(f"! {text}", classes="risk-critical")

            # Next check
            nc = n.get("next_check_at")
            nr = n.get("next_check_reason", "")
            if nc:
                yield Static(f"检查: [cyan]{nc[:16]}[/cyan] {nr}", classes="row")

            # Version selector
            yield Static("")
            yield from self._compose_version_selector(analyses)

    def _compose_version_selector(self, analyses) -> ComposeResult:
        if not analyses or self._version_idx < 0:
            return
        v = analyses[self._version_idx]
        total = len(analyses)
        idx = self._version_idx + 1
        ts = v.created_at[5:16].replace("T", " ")

        # Price from snapshot
        price_note = ""
        if v.prices_snapshot:
            first = next(iter(v.prices_snapshot.values()), {})
            snap_yes = first.get("yes") if isinstance(first, dict) else None
            if snap_yes is not None:
                price_note = f"YES {snap_yes:.2f}"

        trigger_map = {
            "manual": "手动", "scheduled": "定时",
            "movement": "异动", "scan": "扫描",
        }
        trigger_label = trigger_map.get(v.trigger_source, v.trigger_source)
        yield Static(
            f"[dim]v{v.version} ({ts}) {price_note} [{trigger_label}] ({idx}/{total}) 按v切换[/dim]",
            classes="row",
        )

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
                if current_mr and entry > 0:
                    current = (
                        current_mr.yes_price
                        if side == "YES"
                        else current_mr.no_price
                    )
                    if current is not None:
                        shares = size / entry
                        unrealized = shares * current - size
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
