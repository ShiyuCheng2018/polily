"""PortfolioView: open positions with P&L from DB (poll-updated prices)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.pnl import calc_unrealized_pnl
from scanner.tui.service import ScanService

logger = logging.getLogger(__name__)


class ViewTradeDetail(Message):
    """Request to view trade's event detail."""

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class PaperStatusView(Widget):
    """Portfolio view — reads prices from DB (no independent API fetch)."""

    DEFAULT_CSS = """
    PaperStatusView { height: 1fr; }
    PaperStatusView #portfolio-title { padding: 1 0 0 0; text-style: bold; }
    PaperStatusView #portfolio-summary { padding: 0 0 1 2; color: $text-muted; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service
        self._trades: list[dict] = []

    def compose(self) -> ComposeResult:
        yield Static(" 持仓", id="portfolio-title")
        yield Static("", id="portfolio-summary")
        yield DataTable(id="portfolio-table")

    def on_mount(self) -> None:
        self._trades = self.service.get_open_trades()

        table = self.query_one("#portfolio-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("事件", "方向", "入场价", "现价", "P&L", "金额")

        if not self._trades:
            self.query_one("#portfolio-summary", Static).update(
                " [dim]暂无持仓。在市场详情页按 t 标记 paper trade。[/dim]"
            )
            return

        self._fill_table(table)

    def _get_market_price(self, market_id: str) -> float | None:
        """Get current YES price from DB markets table."""
        from scanner.core.event_store import get_market

        m = get_market(market_id, self.service.db)
        return m.yes_price if m else None

    def _fill_table(self, table: DataTable) -> None:
        """Fill portfolio table from DB data."""
        total_value = 0.0
        total_pnl = 0.0
        total_cost = 0.0

        for t in self._trades:
            side = t["side"]
            entry = t["entry_price"]
            size = t["position_size_usd"]
            title = (t["title"] or "")[:30]

            yes_price = self._get_market_price(t["market_id"])

            if yes_price is not None and entry > 0:
                pnl_data = calc_unrealized_pnl(side, entry, yes_price, size)
                cur = yes_price if side == "yes" else round(1 - yes_price, 3)
                pnl_val = pnl_data["pnl"]
                pnl_pct = pnl_data["pnl_pct"]
                value = pnl_data["current_value"]

                cur_str = f"${cur:.2f}"

                if pnl_val > 0:
                    pnl_str = f"[green]+${pnl_val:.2f} (+{pnl_pct:.1f}%)[/green]"
                elif pnl_val < 0:
                    pnl_str = f"[red]-${abs(pnl_val):.2f} ({pnl_pct:.1f}%)[/red]"
                else:
                    pnl_str = "$0.00"

                total_value += value
                total_pnl += pnl_val
                total_cost += size
            else:
                cur_str = "?"
                pnl_str = "-"
                total_cost += size

            entry_str = f"${entry:.2f}"
            amount_str = f"${size:.0f}"

            table.add_row(
                title,
                side.upper(),
                entry_str,
                cur_str,
                pnl_str,
                amount_str,
                key=t["id"],
            )

        # Summary bar
        pnl_pct_total = total_pnl / total_cost * 100 if total_cost > 0 else 0
        pnl_color = "green" if total_pnl >= 0 else "red"

        import contextlib

        with contextlib.suppress(Exception):
            self.query_one("#portfolio-summary", Static).update(
                f" 总计: {len(self._trades)} | "
                f"持仓价值: ${total_value:.2f} | "
                f"浮动盈亏: [{pnl_color}]{'+' if total_pnl >= 0 else ''}"
                f"${total_pnl:.2f} ({pnl_pct_total:+.1f}%)[/{pnl_color}]"
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not event.row_key or not event.row_key.value:
            return
        trade_id = event.row_key.value
        for t in self._trades:
            if t["id"] == trade_id:
                self.post_message(ViewTradeDetail(t["event_id"]))
                return

    def _format_entry_time(self, marked_at: str) -> str:
        """Format entry time as 'MM-DD (Xd)'."""
        try:
            dt = datetime.fromisoformat(marked_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            days = (datetime.now(UTC) - dt).total_seconds() / 86400
            return f"{dt.strftime('%m-%d')} ({days:.0f}天)"
        except (ValueError, TypeError):
            return "?"
