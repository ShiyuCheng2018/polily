"""PaperStatusView: shows open paper trades with position phase status."""

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.position_phase import PHASE_LABELS, compute_position_phase
from scanner.tui.service import ScanService


class AnalyzePositionRequested(Message):
    """Request to run position analysis from paper status page."""
    def __init__(self, trade_id: str):
        super().__init__()
        self.trade_id = trade_id


class PaperStatusView(Widget):
    """Paper trading positions with status labels."""

    BINDINGS = [
        Binding("a", "analyze_position", "持仓分析"),
    ]

    DEFAULT_CSS = """
    PaperStatusView { height: 1fr; }
    PaperStatusView #paper-title { padding: 1 0 0 0; text-style: bold; }
    PaperStatusView #paper-stats { padding: 1 0; color: $text-muted; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._trades = []

    def compose(self) -> ComposeResult:
        yield Static(" 持仓", id="paper-title")
        yield Static("", id="paper-stats")
        yield DataTable(id="paper-table")

    def on_mount(self) -> None:
        table = self.query_one("#paper-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("市场", "方向", "入场价", "状态", "持仓天数")

        self._trades = self.service.get_paper_trades()
        now = datetime.now(UTC)

        for t in self._trades:
            # Calculate days held
            try:
                marked = datetime.fromisoformat(t.marked_at)
                days_held = (now - marked).total_seconds() / 86400
            except (ValueError, TypeError):
                days_held = 0

            # Get current price from latest scan data (best effort)
            current_price = self._get_current_price(t.market_id) or t.entry_price

            # Compute phase
            phase = compute_position_phase(
                entry_price=t.entry_price,
                current_price=current_price,
                side=t.side,
                days_held=days_held,
            )
            phase_label = PHASE_LABELS.get(phase, phase)

            table.add_row(
                t.title[:35],
                t.side.upper(),
                f"{t.entry_price:.2f}",
                phase_label,
                f"{days_held:.1f}天",
                key=t.id,
            )

        if not self._trades:
            stats_widget = self.query_one("#paper-stats", Static)
            stats_widget.update(" [dim]暂无持仓。在市场详情页按 y/n 标记 paper trade。[/dim]")
        else:
            stats = self.service.get_paper_stats()
            stats_widget = self.query_one("#paper-stats", Static)
            stats_widget.update(
                f" 总计: {stats['total_trades']} | 持仓: {stats['open']} | "
                f"已结算: {stats['resolved']} | 胜率: {stats['win_rate']:.0%} | "
                f"PnL: ${stats['total_paper_pnl']:+.2f}\n"
                f" [dim]按 a 对选中持仓进行 AI 分析[/dim]"
            )

    def _get_current_price(self, market_id: str) -> float | None:
        """Get current YES price from latest scan data (best effort, not real-time)."""
        candidates = self.service.get_all_candidates()
        for c in candidates:
            if c.market.market_id == market_id:
                return c.market.yes_price
        return None

    # Note: real-time price fetching available via service.fetch_current_prices()
    # Currently using scan data for phase calculation. Real-time fetch can be
    # triggered by the user via position analysis (pressing 'a').

    def action_analyze_position(self) -> None:
        """Trigger position analysis for selected trade."""
        if not self._trades:
            return
        try:
            table = self.query_one("#paper-table", DataTable)
            row_idx = table.cursor_row
        except Exception:
            return
        if row_idx < len(self._trades):
            self.post_message(AnalyzePositionRequested(self._trades[row_idx].id))
