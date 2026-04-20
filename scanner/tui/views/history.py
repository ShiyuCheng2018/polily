"""HistoryView: realized-P&L ledger (v0.8.0).

Each SELL or RESOLVE row in `wallet_transactions` is one history entry
(newest first on top). Fed by `ScanService.get_realized_history`
and `get_realized_summary` — the legacy `paper_trades` table is no
longer consulted.

Column set mirrors the mockup the user approved (2026-04-19):
    市场  方向  操作  股数  成交价  P&L  摩擦  时间

v0.8.0 migration:
- PolilyZone atom wraps the list (title: 已实现交易历史)
- Summary + DataTable mounted ONCE in `on_mount`; `_render_all`
  repopulates via `table.clear()` + re-add rows (paper_status lesson:
  Textual's `remove()` is deferred, so re-mounting stable-id widgets
  on the same tick trips DuplicateIds)
- Subscribes to TOPIC_WALLET_UPDATED — every SELL / RESOLVE writes
  to wallet_transactions and publishes this topic, so a mounted
  HistoryView auto-refreshes when the user closes a position
- Q11 NAV_BINDINGS + `r` for manual refresh
- Chinese labels throughout; no internal IDs surfaced (row_keys use
  transaction id but never render in visible cells)
"""

from __future__ import annotations

import contextlib

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.core.events import TOPIC_WALLET_UPDATED
from scanner.tui.bindings import NAV_BINDINGS
from scanner.tui.icons import ICON_COMPLETED
from scanner.tui.service import ScanService
from scanner.tui.widgets.polily_zone import PolilyZone


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


_COLUMN_SPEC = [
    "市场",
    "方向",
    "操作",
    "股数",
    "成交价",
    "P&L",
    "摩擦",
    "时间",
]


class HistoryView(Widget):
    """Realized P&L ledger — one row per SELL / RESOLVE event."""

    BINDINGS = [
        Binding("r", "refresh", "刷新", show=False),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    HistoryView { height: 1fr; }
    HistoryView > VerticalScroll { height: 1fr; }
    HistoryView > VerticalScroll > PolilyZone { height: auto; }
    HistoryView #history-summary { padding: 0 0 1 0; color: $text-muted; }
    HistoryView #history-empty { text-align: center; color: $text-muted; padding: 2; }
    HistoryView DataTable { height: auto; }
    """

    def __init__(self, service: ScanService):
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PolilyZone(
                title=f"{ICON_COMPLETED} 已实现交易历史",
                id="history-zone",
            )

    def on_mount(self) -> None:
        """Mount summary + empty-state + table ONCE inside the zone.

        `_render_all` then refreshes them in place via `table.clear()`
        + re-add rows. Re-mounting per render would leak stale widgets
        because Textual's `remove()` is deferred, tripping DuplicateIds
        on IDs like `#history-table`.
        """
        try:
            zone = self.query_one("#history-zone", PolilyZone)
        except Exception:
            zone = None

        if zone is not None:
            zone.mount(Static("", id="history-summary"))
            zone.mount(Static("", id="history-empty"))
            table = DataTable(id="history-table")
            zone.mount(table)
            table.cursor_type = "row"
            table.add_columns(*_COLUMN_SPEC)

        # Auto-refresh on new realized rows (SELL / RESOLVE both publish
        # TOPIC_WALLET_UPDATED — see wallet.py / resolution.py).
        self.service.event_bus.subscribe(
            TOPIC_WALLET_UPDATED, self._on_wallet_update,
        )

        self._render_all()

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(
            TOPIC_WALLET_UPDATED, self._on_wallet_update,
        )

    # -- Bus callbacks (published from non-UI threads — must hop back) --

    def _on_wallet_update(self, payload: dict) -> None:
        """Bus callback — MUST use call_from_thread (called from non-UI thread)."""
        with contextlib.suppress(Exception):
            self.app.call_from_thread(self._render_all)

    # -- Actions --

    def action_refresh(self) -> None:
        """Manual refresh (Q11 `r` binding) — re-query + rebuild."""
        self._render_all()

    # -- Rendering --

    def _render_all(self) -> None:
        """Refresh summary + DataTable contents in place."""
        try:
            table = self.query_one("#history-table", DataTable)
        except Exception:
            return

        history = self.service.get_realized_history()
        summary = self.service.get_realized_summary()

        table.clear()

        empty_msg: Static | None = None
        with contextlib.suppress(Exception):
            empty_msg = self.query_one("#history-empty", Static)

        if not history:
            with contextlib.suppress(Exception):
                self.query_one("#history-summary", Static).update(
                    "[dim]暂无已实现的交易。[/dim]",
                )
            if empty_msg is not None:
                empty_msg.update("开仓后卖出或市场结算，将在此留下记录。")
                empty_msg.display = True
            return

        if empty_msg is not None:
            empty_msg.display = False

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
        with contextlib.suppress(Exception):
            self.query_one("#history-summary", Static).update(
                f"已实现 {summary['count']} 笔 · "
                f"累计 P&L [{pnl_color}]{pnl_sign}${summary['total_pnl']:.2f}[/{pnl_color}] · "
                f"累计摩擦 {fees_str}",
            )
