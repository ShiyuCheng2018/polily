"""PortfolioView: open positions with P&L from DB (poll-updated prices).

v0.8.0 migration:
- PolilyZone atom wraps the portfolio section (title: 持仓)
- EventBus subscriptions (TOPIC_WALLET_UPDATED, TOPIC_POSITION_UPDATED,
  TOPIC_PRICE_UPDATED) drive auto-refresh on mutations
- Q11 NAV_BINDINGS + view-specific bindings (enter, r)
- Chinese labels throughout; internal market_id / event_id not surfaced in
  visible cells (row_keys preserved for the ViewTradeDetail routing)

Scope note (v0.8.0 Q7b): this view overlaps conceptually with WalletView
(both surface paper-trade state). The two are not merged in v0.8.0; a
v0.9.0 consolidation is on the roadmap.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widget import Widget
from textual.widgets import DataTable, Static

from polily.core.events import (
    TOPIC_LANGUAGE_CHANGED,
    TOPIC_POSITION_UPDATED,
    TOPIC_PRICE_UPDATED,
    TOPIC_WALLET_UPDATED,
)
from polily.pnl import calc_unrealized_pnl
from polily.tui._dispatch import once_per_tick
from polily.tui.bindings import NAV_BINDINGS
from polily.tui.i18n import t as _t  # `t` collides with `for t in self._trades:` loops
from polily.tui.icons import ICON_POSITION
from polily.tui.service import PolilyService
from polily.tui.widgets.polily_zone import PolilyZone

logger = logging.getLogger(__name__)


# Stable internal column key -> catalog key for the visible label.
# NOTE: the legacy "现价" key is preserved as the table-cell update key
# (paper_status._fill_table writes to update_cell(..., "现价", ...) — keep
# that key string stable across the i18n migration so existing call sites
# don't break).
_COLUMN_SPEC = [
    ("title", "paper.col.event"),
    ("side", "paper.col.side"),
    ("entry", "paper.col.entry"),
    ("现价", "paper.col.current"),
    ("amount", "paper.col.amount"),
    ("value", "paper.col.value"),
    ("P&L", "paper.col.pnl"),
]


class ViewTradeDetail(Message):
    """Request to view trade's event detail."""

    def __init__(self, event_id: str):
        super().__init__()
        self.event_id = event_id


class PaperStatusView(Widget):
    """Portfolio view — reads prices from DB (no independent API fetch)."""

    # NOTE: I18nFooter renders binding labels via t(f"binding.{action}") at
    # compose time, so the zh strings below are only fallbacks.
    BINDINGS = [
        Binding("enter", "view_detail", "详情", show=True),
        Binding("r", "refresh", "刷新", show=True),
        *NAV_BINDINGS,
    ]

    DEFAULT_CSS = """
    PaperStatusView { height: 1fr; }
    PaperStatusView > VerticalScroll { height: 1fr; }
    /* v0.8.0+: stretch 持仓 zone to screen bottom so the list extends
       naturally instead of collapsing to content height. */
    PaperStatusView > VerticalScroll > PolilyZone { height: 1fr; }
    PaperStatusView DataTable { height: 1fr; }
    """

    def __init__(self, service: PolilyService):
        super().__init__()
        self.service = service
        self._trades: list[dict] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield PolilyZone(
                title=f"{ICON_POSITION} {_t('paper.title.zone')}",
                id="portfolio-zone",
            )

    def on_mount(self) -> None:
        # Mount summary + table once inside the zone; `_render_all` then
        # repopulates them in place. Re-mounting on each render leaks
        # stale widgets because Textual's `remove()` is deferred, which
        # trips DuplicateIds on IDs like `#portfolio-summary`.
        try:
            zone = self.query_one("#portfolio-zone", PolilyZone)
        except Exception:
            zone = None

        if zone is not None:
            zone.mount(Static("", id="portfolio-summary", classes="pb-sm text-muted"))
            table = DataTable(id="portfolio-table")
            zone.mount(table)
            table.cursor_type = "row"
            for col_key, cat_key in _COLUMN_SPEC:
                table.add_column(_t(cat_key), key=col_key)

        self.service.event_bus.subscribe(
            TOPIC_WALLET_UPDATED, self._on_wallet_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_POSITION_UPDATED, self._on_position_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self.service.event_bus.subscribe(
            TOPIC_LANGUAGE_CHANGED, self._on_lang_changed,
        )
        # Initial render bypasses @once_per_tick — callers expect
        # synchronous population by the time on_mount returns.
        type(self)._render_all.__wrapped__(self)

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(
            TOPIC_WALLET_UPDATED, self._on_wallet_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_POSITION_UPDATED, self._on_position_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_PRICE_UPDATED, self._on_price_update,
        )
        self.service.event_bus.unsubscribe(
            TOPIC_LANGUAGE_CHANGED, self._on_lang_changed,
        )

    def _on_lang_changed(self, payload: dict) -> None:
        """Update zone title + DataTable column headers on language switch.
        Row content + summary line are re-rendered by _render_all."""
        with contextlib.suppress(Exception):
            self.query_one("#portfolio-zone .polily-zone-title", Static).update(
                f"{ICON_POSITION} {_t('paper.title.zone')}",
            )
            table = self.query_one("#portfolio-table", DataTable)
            for col_key, cat_key in _COLUMN_SPEC:
                if col_key in table.columns:
                    # pyright complains about str → ColumnKey + str → Text;
                    # both work at runtime (see wallet.py for the same note).
                    table.columns[col_key].label = _t(cat_key)  # pyright: ignore[reportArgumentType, reportAttributeAccessIssue]
            table.refresh()
        self._render_all()

    # -- Bus callbacks (published from non-UI threads — must hop back) --

    def _on_wallet_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self._render_all()  # coalesced by @once_per_tick

    def _on_position_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self._render_all()  # coalesced by @once_per_tick

    def _on_price_update(self, payload: dict) -> None:
        with contextlib.suppress(Exception):
            self._render_all()  # coalesced by @once_per_tick

    # -- Rendering --

    def _get_market_price(self, market_id: str) -> float | None:
        """Get current YES price from DB markets table."""
        from polily.core.event_store import get_market

        m = get_market(market_id, self.service.db)
        return m.yes_price if m else None

    @once_per_tick
    def _render_all(self) -> None:
        """Refresh the summary + DataTable contents in place.

        Table + summary are mounted once in `on_mount`; here we just clear
        rows + update summary text. This avoids remove() race conditions
        with Textual's deferred node removal.

        `@once_per_tick`: subscribes to 3 bus topics (WALLET+POSITION+
        PRICE) — heartbeat fan-out would otherwise trigger 3× per tick.
        """
        try:
            table = self.query_one("#portfolio-table", DataTable)
        except Exception:
            return

        self._trades = self.service.get_open_trades()
        table.clear()

        if not self._trades:
            with contextlib.suppress(Exception):
                self.query_one("#portfolio-summary", Static).update(_t("paper.empty"))
            return

        self._fill_table(table)

    def _fill_table(self, table: DataTable) -> None:
        """Fill portfolio table from DB data + update summary line."""
        total_value = 0.0
        total_pnl = 0.0
        total_cost = 0.0

        for t in self._trades:
            side = t["side"]
            entry = t["entry_price"]
            size = t["position_size_usd"]
            title = (t["title"] or "")[:30]

            yes_price = self._get_market_price(t["market_id"])

            shares = size / entry if entry > 0 else 0

            if yes_price is not None and entry > 0:
                pnl_data = calc_unrealized_pnl(side, entry, yes_price, size)
                cur = yes_price if side == "yes" else round(1 - yes_price, 3)
                pnl_val = pnl_data["pnl"]
                pnl_pct = pnl_data["pnl_pct"]
                value = pnl_data["current_value"]

                cur_str = f"{cur * 100:.1f}¢"
                value_str = f"${value:.2f}"

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
                value_str = "?"
                total_cost += size

            entry_str = f"{entry * 100:.1f}¢"
            amount_str = _t("paper.amount_format", size=size, shares=shares)

            table.add_row(
                title,
                side.upper(),
                entry_str,
                cur_str,
                amount_str,
                value_str,
                pnl_str,
                key=t["id"],
            )

        # Summary line
        pnl_pct_total = total_pnl / total_cost * 100 if total_cost > 0 else 0
        pnl_color = "green" if total_pnl >= 0 else "red"
        pnl_sign = "+" if total_pnl >= 0 else ""

        with contextlib.suppress(Exception):
            self.query_one("#portfolio-summary", Static).update(
                _t(
                    "paper.summary",
                    count=len(self._trades),
                    value=total_value,
                    pnl_color=pnl_color,
                    pnl_sign=pnl_sign,
                    pnl=total_pnl,
                    pnl_pct=pnl_pct_total,
                )
            )

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if not event.row_key or not event.row_key.value:
            return
        trade_id = event.row_key.value
        for t in self._trades:
            if t["id"] == trade_id:
                self.post_message(ViewTradeDetail(t["event_id"]))
                return

    def action_view_detail(self) -> None:
        """Enter: navigate to event detail for selected row."""
        try:
            table = self.query_one("#portfolio-table", DataTable)
        except Exception:
            return
        row = table.cursor_row
        if row is None or row < 0 or row >= len(self._trades):
            return
        self.post_message(ViewTradeDetail(self._trades[row]["event_id"]))

    def action_refresh(self) -> None:
        """Manual refresh (Q11 `r` binding) — full rebuild."""
        self._render_all()

    def refresh_data(self) -> None:
        """Re-query positions, then update prices and P&L for visible rows.

        Re-queries because positions can change between mounts: auto-resolution
        via poll_job deletes closed positions, reset_wallet clears all, and
        future UI paths may add trades without re-mounting this view. If the
        set of row keys changed, rebuild the whole table — otherwise just
        refresh cells incrementally to preserve cursor position.
        """
        try:
            table = self.query_one("#portfolio-table", DataTable)
        except Exception:
            # Table absent → either empty state mounted or not composed yet.
            # Fall back to full render which handles both paths.
            type(self)._render_all.__wrapped__(self)  # sync: bypass @once_per_tick
            return

        fresh = self.service.get_open_trades()
        old_keys = {t["id"] for t in self._trades}
        new_keys = {t["id"] for t in fresh}
        self._trades = fresh

        if old_keys != new_keys:
            # Row set changed → rebuild everything so DataTable doesn't hold
            # stale row_keys pointing at deleted / missing positions.
            type(self)._render_all.__wrapped__(self)  # sync: bypass @once_per_tick
            return

        if not self._trades:
            return

        total_value = 0.0
        total_pnl = 0.0
        total_cost = 0.0

        for t in self._trades:
            side = t["side"]
            entry = t["entry_price"]
            size = t["position_size_usd"]
            yes_price = self._get_market_price(t["market_id"])

            if yes_price is not None and entry > 0:
                pnl_data = calc_unrealized_pnl(side, entry, yes_price, size)
                cur = yes_price if side == "yes" else round(1 - yes_price, 3)
                pnl_val = pnl_data["pnl"]
                pnl_pct = pnl_data["pnl_pct"]
                value = pnl_data["current_value"]

                cur_str = f"{cur * 100:.1f}¢"
                value_str = f"${value:.2f}"
                if pnl_val > 0:
                    pnl_str = f"[green]+${pnl_val:.2f} (+{pnl_pct:.1f}%)[/green]"
                elif pnl_val < 0:
                    pnl_str = f"[red]-${abs(pnl_val):.2f} ({pnl_pct:.1f}%)[/red]"
                else:
                    pnl_str = "$0.00"

                total_value += value
                total_pnl += pnl_val
            else:
                cur_str = "?"
                pnl_str = "-"
                value_str = "?"
            total_cost += size

            with contextlib.suppress(Exception):
                table.update_cell(t["id"], "现价", cur_str)
                table.update_cell(t["id"], "value", value_str)
                table.update_cell(t["id"], "P&L", pnl_str)

        # Update summary
        pnl_pct_total = total_pnl / total_cost * 100 if total_cost > 0 else 0
        pnl_color = "green" if total_pnl >= 0 else "red"
        pnl_sign = "+" if total_pnl >= 0 else ""
        with contextlib.suppress(Exception):
            self.query_one("#portfolio-summary", Static).update(
                _t(
                    "paper.summary",
                    count=len(self._trades),
                    value=total_value,
                    pnl_color=pnl_color,
                    pnl_sign=pnl_sign,
                    pnl=total_pnl,
                    pnl_pct=pnl_pct_total,
                )
            )

    def _format_entry_time(self, marked_at: str) -> str:
        """Format entry time as 'MM-DD (Xd)'."""
        try:
            dt = datetime.fromisoformat(marked_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            days = (datetime.now(UTC) - dt).total_seconds() / 86400
            return _t("paper.due_format", date=dt.strftime("%m-%d"), days=days)
        except (ValueError, TypeError):
            return "?"
