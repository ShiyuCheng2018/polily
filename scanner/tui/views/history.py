"""HistoryView: resolved paper trades with settlement results and P&L."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.service import ScanService


class HistoryView(Widget):
    """History of resolved paper trades."""

    DEFAULT_CSS = """
    HistoryView { height: 1fr; }
    HistoryView #history-title { padding: 1 0 0 0; text-style: bold; }
    HistoryView #history-summary { padding: 0 0 1 2; color: $text-muted; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield Static(" 历史", id="history-title")
        yield Static("", id="history-summary")
        yield DataTable(id="history-table")

    def on_mount(self) -> None:
        trades = self.service.get_resolved_trades()
        stats = self.service.get_trade_stats()

        table = self.query_one("#history-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("市场", "方向", "入场", "结算", "P&L", "扣摩擦", "P&L%", "结算时间")

        if not trades:
            self.query_one("#history-summary", Static).update(
                " [dim]暂无已结算的持仓。[/dim]"
            )
            return

        for t in trades:
            side = t["side"]
            entry_price = t["entry_price"]
            position_size_usd = t["position_size_usd"]
            resolved_result = t.get("resolved_result")

            # Settlement price: win -> 1.00, lose -> 0.00
            if resolved_result:
                won = side == resolved_result
                settle_price = "1.00" if won else "0.00"
            else:
                settle_price = "?"

            # P&L -- each colored independently
            pnl = t.get("paper_pnl") or 0
            friction_pnl = t.get("friction_adjusted_pnl") or 0

            if pnl > 0:
                pnl_str = f"[green]+${pnl:.2f}[/green]"
            elif pnl < 0:
                pnl_str = f"[red]-${abs(pnl):.2f}[/red]"
            else:
                pnl_str = "$0.00"

            if friction_pnl > 0:
                friction_str = f"[green]+${friction_pnl:.2f}[/green]"
            elif friction_pnl < 0:
                friction_str = f"[red]-${abs(friction_pnl):.2f}[/red]"
            else:
                friction_str = "$0.00"

            # P&L %
            pnl_pct = pnl / position_size_usd * 100 if position_size_usd > 0 else 0
            if pnl_pct > 0:
                pnl_pct_str = f"[green]+{pnl_pct:.1f}%[/green]"
            elif pnl_pct < 0:
                pnl_pct_str = f"[red]{pnl_pct:.1f}%[/red]"
            else:
                pnl_pct_str = "0.0%"

            # Resolved time
            resolved_at = t.get("resolved_at", "?")
            resolved_at = resolved_at[:10] if resolved_at else "?"

            table.add_row(
                (t.get("title") or "?")[:30],
                side.upper(),
                f"{entry_price:.2f}",
                settle_price,
                pnl_str,
                friction_str,
                pnl_pct_str,
                resolved_at,
                key=t["id"],
            )

        # Summary
        win_pct = stats["win_rate"] * 100
        total_pnl = stats["total_pnl"]
        total_friction = stats["total_friction_pnl"]

        pnl_color = "green" if total_pnl >= 0 else "red"

        self.query_one("#history-summary", Static).update(
            f" 已结算: {stats['resolved']} | "
            f"胜率: {win_pct:.0f}% | "
            f"PnL: [{pnl_color}]{'+' if total_pnl >= 0 else ''}${total_pnl:.2f}[/{pnl_color}] | "
            f"扣摩擦: [{pnl_color}]{'+' if total_friction >= 0 else ''}${total_friction:.2f}[/{pnl_color}]"
        )
