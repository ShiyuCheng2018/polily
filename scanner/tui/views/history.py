"""HistoryView: realized-P&L ledger (v0.6.0).

Each SELL or RESOLVE row in `wallet_transactions` is one history entry
(oldest first on the bottom). Fed by `ScanService.get_realized_history`
and `get_realized_summary` — the legacy `paper_trades` table is no
longer consulted.

Column set mirrors the mockup the user approved (2026-04-19):
    市场  方向  操作  股数  成交价  P&L  摩擦  时间
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.tui.service import ScanService


def _fmt_pnl(value: float) -> str:
    if value > 0:
        return f"[green]+${value:.2f}[/green]"
    if value < 0:
        return f"[red]-${abs(value):.2f}[/red]"
    return "$0.00"


def _fmt_time(created_at: str) -> str:
    """Trim ISO timestamp to MM-DD HH:MM for column display."""
    # created_at is always ISO 8601 from wallet._insert_tx.
    try:
        return f"{created_at[5:10]} {created_at[11:16]}"
    except (IndexError, TypeError):
        return "?"


class HistoryView(Widget):
    """Realized P&L ledger — one row per SELL / RESOLVE event."""

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
        history = self.service.get_realized_history()
        summary = self.service.get_realized_summary()

        table = self.query_one("#history-table", DataTable)
        table.cursor_type = "row"
        table.add_columns(
            "市场", "方向", "操作", "股数", "成交价", "P&L", "摩擦", "时间",
        )

        if not history:
            self.query_one("#history-summary", Static).update(
                " [dim]暂无已实现的交易。[/dim]",
            )
            return

        for row in history:
            title = (row.get("title") or "?")[:30]
            side = (row.get("side") or "?").upper()
            tx_type = row.get("type", "?")
            shares = row.get("shares") or 0
            price = row.get("price") or 0
            pnl = row.get("realized_pnl") or 0
            fee = row.get("fee_usd") or 0

            fee_str = f"${fee:.2f}" if fee > 0 else "-"

            table.add_row(
                title,
                side,
                tx_type,
                f"{shares:.0f}",
                f"${price:.2f}",
                _fmt_pnl(pnl),
                fee_str,
                _fmt_time(row.get("created_at", "")),
                key=str(row["id"]),
            )

        pnl_color = "green" if summary["total_pnl"] >= 0 else "red"
        pnl_sign = "+" if summary["total_pnl"] >= 0 else ""
        fees_str = (
            f"${summary['total_fees']:.2f}"
            if summary["total_fees"] > 0 else "$0.00"
        )
        self.query_one("#history-summary", Static).update(
            f" 已实现 {summary['count']} 笔 · "
            f"累计 P&L [{pnl_color}]{pnl_sign}${summary['total_pnl']:.2f}[/{pnl_color}] · "
            f"累计摩擦 {fees_str}",
        )
