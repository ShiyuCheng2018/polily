"""PaperStatusView: shows open paper trades and stats."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.service import ScanService


class PaperStatusView(Widget):
    """Paper trading positions and performance summary."""

    DEFAULT_CSS = """
    PaperStatusView { height: 1fr; }
    PaperStatusView #paper-title { padding: 1 0 0 0; text-style: bold; }
    PaperStatusView #paper-stats { padding: 1 0; color: $text-muted; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield Static(" 📝 Paper 持仓", id="paper-title")
        yield Static("", id="paper-stats")
        yield DataTable(id="paper-table")

    def on_mount(self) -> None:
        table = self.query_one("#paper-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("ID", "市场", "方向", "价格", "标记日期")

        trades = self.service.get_paper_trades()
        for t in trades:
            table.add_row(
                t.id,
                t.title[:40],
                t.side.upper(),
                f"{t.entry_price:.2f}",
                t.marked_at[:10],
                key=t.id,
            )

        if not trades:
            stats_widget = self.query_one("#paper-stats", Static)
            stats_widget.update(" [dim]暂无持仓。用 y/n 键在市场列表中标记 paper trade。[/dim]")
        else:
            stats = self.service.get_paper_stats()
            stats_widget = self.query_one("#paper-stats", Static)
            stats_widget.update(
                f" 总计: {stats['total_trades']} | 持仓: {stats['open']} | "
                f"已结算: {stats['resolved']} | 胜率: {stats['win_rate']:.0%} | "
                f"PnL: ${stats['total_paper_pnl']:+.2f}"
            )
