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
        Binding("y", "trade_yes", "买 YES", show=True),
        Binding("n", "trade_no", "买 NO", show=True),
        Binding("o", "open_link", "打开链接", show=True),
    ]

    DEFAULT_CSS = """
    MarketListView { height: 1fr; }
    MarketListView #list-title { padding: 1 0 0 0; text-style: bold; }
    MarketListView .empty-msg { text-align: center; color: $text-muted; padding: 4; }
    """

    def __init__(self, candidates: list[ScoredCandidate], service: ScanService, title: str = "市场"):
        super().__init__()
        self.candidates = candidates
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
        table.add_columns("市场", "类型", "YES", "结构分", "结算", "价差", "AI")
        for c in self.candidates:
            m = c.market
            days = f"{m.days_to_resolution:.1f}天" if m.days_to_resolution else "?"
            spread = f"{m.spread_pct_yes:.1%}" if m.spread_pct_yes else "?"
            mtype = m.market_type or "other"
            title = m.title[:40] + "..." if len(m.title) > 40 else m.title
            ai_tag = "v" if c.narrative else ""
            table.add_row(
                title,
                mtype,
                f"{m.yes_price:.2f}" if m.yes_price else "?",
                f"{c.score.total:.0f}",
                days,
                spread,
                ai_tag,
                key=m.market_id,
            )

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

    def action_open_link(self) -> None:
        c = self._get_selected()
        if c:
            import webbrowser
            try:
                webbrowser.open(c.market.polymarket_url)
            except Exception:
                self.notify("无法打开浏览器", severity="warning")
