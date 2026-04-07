"""MarketListView: browsable market table with paper trade actions."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.reporting import ScoredCandidate
from scanner.tui.service import ScanService


class ViewDetailRequested(Message):
    """Request to view market detail."""
    def __init__(self, candidate: ScoredCandidate):
        super().__init__()
        self.candidate = candidate


class MarketListView(Widget):
    """Market list with inline actions."""

    BINDINGS = [
        Binding("enter", "view_detail", "详情"),
        Binding("y", "trade_yes", "买 YES"),
        Binding("n", "trade_no", "买 NO"),
        Binding("p", "quick_pass", "PASS"),
        Binding("o", "open_link", "打开链接"),
    ]

    DEFAULT_CSS = """
    MarketListView { height: 1fr; }
    MarketListView #list-title { padding: 1 0 0 0; text-style: bold; }
    MarketListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, candidates: list[ScoredCandidate], service: ScanService, title: str = "市场"):
        super().__init__()
        # Sort by value score descending
        from scanner.scoring import compute_three_scores
        self.candidates = sorted(
            candidates,
            key=lambda c: compute_three_scores(c.score, c.mispricing, c.market).get("value", 0),
            reverse=True,
        )
        self.service = service
        self._title = title

    def compose(self) -> ComposeResult:
        yield Static(f" {self._title} ({len(self.candidates)})", id="list-title")
        if not self.candidates:
            yield Static(" 今天没有候选市场。好机会不是每天都有，休息也是策略。", classes="empty-msg")
        else:
            yield DataTable(id="market-table")

    def on_mount(self) -> None:
        if not self.candidates:
            return
        table = self.query_one("#market-table", DataTable)
        table.cursor_type = "row"
        from scanner.scoring import compute_three_scores
        table.add_columns("市场", "质量", "价值", "动作", "YES", "NO", "结算", "类型")
        seen_ids: set[str] = set()
        for idx, c in enumerate(self.candidates):
            m = c.market
            n = c.narrative
            from scanner.tui.utils import format_countdown
            res_time = m.resolution_time.isoformat() if m.resolution_time else None
            days = format_countdown(res_time)
            title = m.title[:38] + "..." if len(m.title) > 38 else m.title

            # Three scores
            three = compute_three_scores(c.score, c.mispricing, m)
            quality = f"{three['quality']:.0f}"
            value = f"{three['value']:.0f}"

            # Action from AI narrative (if analyzed)
            action_map = {
                "small_position_ok": "GO",
                "worth_research": "RESEARCH",
                "watch_only": "WATCH",
                "avoid": "AVOID",
                "BUY_YES": "BUY YES",
                "BUY_NO": "BUY NO",
                "PASS": "PASS",
                "WATCH": "WATCH",
            }
            action = action_map.get(getattr(n, "action", ""), "-") if n else "-"

            no_price = round(1 - m.yes_price, 2) if m.yes_price else None
            table.add_row(
                title,
                quality,
                value,
                action,
                f"{m.yes_price:.2f}" if m.yes_price else "?",
                f"{no_price:.2f}" if no_price is not None else "?",
                days,
                m.market_type or "other",
                key=m.market_id if m.market_id not in seen_ids else f"{m.market_id}_{idx}",
            )
            seen_ids.add(m.market_id)

    def _get_selected(self) -> ScoredCandidate | None:
        if not self.candidates:
            return None
        try:
            table = self.query_one("#market-table", DataTable)
        except Exception:
            return None
        row = table.cursor_row
        if row >= len(self.candidates):
            return None
        return self.candidates[row]

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Enter key on DataTable row — open detail view."""
        c = self._get_selected()
        if c:
            self.post_message(ViewDetailRequested(c))

    def action_trade_yes(self) -> None:
        self._do_trade("yes")

    def action_trade_no(self) -> None:
        self._do_trade("no")

    def _do_trade(self, side: str):
        c = self._get_selected()
        if not c:
            self.notify("请先选择一个市场", severity="warning")
            return

        m = c.market
        if side == "yes":
            price = m.yes_price
        else:
            price = m.no_price if m.no_price is not None else (1 - (m.yes_price or 0.5))

        if not price or price <= 0:
            self.notify("价格无效", severity="error")
            return

        # Double-press confirm: first press sets pending, second executes
        if hasattr(self, "_pending_trade") and self._pending_trade == (m.market_id, side):
            trade_id = self.service.mark_paper_trade(
                market_id=m.market_id, title=m.title, side=side,
                price=price, market_type=m.market_type, score=c.score.total,
            )
            self.notify(f"Paper trade: {side.upper()} @ {price:.2f} -> {trade_id}")
            self._pending_trade = None
            self.screen.refresh_sidebar_counts()
        else:
            self._pending_trade = (m.market_id, side)
            title_short = m.title[:30]
            self.notify(f"再按一次 {side[0]} 确认: {side.upper()} {title_short} @ {price:.2f}")

    def action_quick_pass(self) -> None:
        c = self._get_selected()
        if not c:
            return
        from datetime import UTC, datetime

        from scanner.market_state import MarketState, get_market_state, set_market_state
        mid = c.market.market_id
        state = get_market_state(mid, self.service.db)
        if state is None:
            state = MarketState(status="pass", title=c.market.title)
        state.status = "pass"
        state.updated_at = datetime.now(UTC).isoformat()
        state.auto_monitor = False
        state.next_check_at = None
        set_market_state(mid, state, self.service.db)
        from scanner.auto_monitor import cleanup_closed_market
        cleanup_closed_market(mid)
        self.notify(f"PASS: {c.market.title[:30]}")
        self.screen.refresh_sidebar_counts()

    def action_view_detail(self) -> None:
        c = self._get_selected()
        if c:
            self.post_message(ViewDetailRequested(c))

    def action_open_link(self) -> None:
        c = self._get_selected()
        if c:
            import webbrowser
            try:
                webbrowser.open(c.market.polymarket_url)
            except Exception:
                self.notify("无法打开浏览器", severity="warning")
