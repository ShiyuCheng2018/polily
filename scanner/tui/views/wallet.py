"""WalletView: balance panel + transactions ledger.

v0.8.0 changes:
- PolilyCard for balance summary (余额概览)
- PolilyZone for transactions ledger (交易流水)
- Event bus subscription (TOPIC_WALLET_UPDATED, TOPIC_POSITION_UPDATED) for auto-refresh
- BINDINGS: keep t/w, add r (reset) with show=True per SF4 decision
- NAV_BINDINGS appended for Q11 key spec compliance

Keybindings
    t        TopupModal
    w        WithdrawModal
    shift+r  WalletResetModal (r is reserved for global refresh;
             Shift modifier prevents accidental destructive resets)

Data lives in `positions` and `wallet_transactions`; prices are read from
`markets.yes_price` (poll-updated ~30s). The `cumulative_realized_pnl`
surfaced on the snapshot is derived from SELL+RESOLVE rows so it stays
consistent even across resets.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Button, DataTable, Static

from scanner.core.events import (
    TOPIC_POSITION_UPDATED,
    TOPIC_WALLET_UPDATED,
    dispatch_to_ui,
)
from scanner.tui.bindings import NAV_BINDINGS
from scanner.tui.icons import ICON_WALLET
from scanner.tui.service import ScanService
from scanner.tui.views._wallet_overview import compute_wallet_overview
from scanner.tui.widgets.kv_row import KVRow
from scanner.tui.widgets.polily_card import PolilyCard
from scanner.tui.widgets.polily_zone import PolilyZone

logger = logging.getLogger(__name__)


_TX_TYPE_LABEL = {
    "TOPUP": "充值",
    "WITHDRAW": "提现",
    "BUY": "买入",
    "SELL": "卖出",
    "FEE": "手续费",
    "RESOLVE": "结算",
    "MIGRATION": "初始化 v0.6.0",
}


def _format_tx_description(tx: dict) -> str:
    """Condense one wallet_transactions row into '说明' column text."""
    t = tx["type"]
    label = _TX_TYPE_LABEL.get(t, t)
    # Topup / Withdraw / Migration — just the label + any notes.
    if t in ("TOPUP", "WITHDRAW", "MIGRATION"):
        return label + (f"  {tx['notes']}" if tx.get("notes") else "")
    # Buy / Sell — add market + side + shares@price.
    if t in ("BUY", "SELL"):
        side = (tx.get("side") or "").upper()
        shares = tx.get("shares")
        price = tx.get("price")
        market = tx.get("market_id") or "?"
        parts = [label, f"{market} {side}"]
        if shares is not None and price is not None:
            parts.append(f"{shares:.1f}股@{price * 100:.1f}¢")
        return "  ".join(parts)
    # Fee — pin to market+side for grouping with the trade.
    if t == "FEE":
        side = (tx.get("side") or "").upper()
        market = tx.get("market_id") or "?"
        return f"{label} ({market} {side})"
    # Resolve — mirror buy/sell shape.
    if t == "RESOLVE":
        side = (tx.get("side") or "").upper()
        market = tx.get("market_id") or "?"
        shares = tx.get("shares")
        if shares is not None:
            return f"{label} {market} {side} {shares:.1f}股"
        return f"{label} {market} {side}"
    return label


def _format_ts(ts: str) -> str:
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return ts[:16]


class WalletView(Widget):
    """Balance summary + transaction ledger + action buttons."""

    DEFAULT_CSS = """
    WalletView { height: 1fr; padding: 1 2; }
    WalletView #balance-card { margin: 0 0 1 0; }
    WalletView #ledger-zone { height: 1fr; }
    WalletView #wallet-table { height: 1fr; }
    WalletView #action-row { height: 3; padding: 0; align: right middle; }
    WalletView #reset-btn {
        width: 14;
        background: $error 20%;
        color: white;
    }
    """

    BINDINGS = [
        Binding("t", "topup", "充值", show=True),
        Binding("w", "withdraw", "提现", show=True),
        Binding("r", "refresh", "刷新", show=True),
        # v0.8.0: `r` is page refresh (every view has it) — reset moves
        # to shift+r so the destructive op keeps a mnemonic key but
        # requires a modifier.
        Binding("shift+r", "reset", "重置", show=True),
        *NAV_BINDINGS,
    ]

    def __init__(self, service: ScanService) -> None:
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield PolilyCard(title=f"{ICON_WALLET} 余额概览", id="balance-card")
        yield PolilyZone(title="交易流水", id="ledger-zone")
        with Horizontal(id="action-row"):
            # v0.8.0: the redundant `[t] 充值   [w] 提现   [r] 重置`
            # hint Static was removed — the Footer already surfaces
            # every binding. Only the destructive red button remains
            # as the primary reset entry point.
            yield Button("重置钱包", id="reset-btn", variant="error", classes="bold")

    def on_mount(self) -> None:
        # Set up ledger table inside ledger zone
        ledger_zone = self.query_one("#ledger-zone", PolilyZone)
        table = DataTable(id="wallet-table")
        ledger_zone.mount(table)
        table.cursor_type = "row"
        table.add_columns(
            ("时间", "time"),
            ("说明", "desc"),
            ("金额", "amount"),
            ("余额", "balance"),
        )
        # Subscribe to event bus topics
        self.service.event_bus.subscribe(TOPIC_WALLET_UPDATED, self._on_wallet_update)
        self.service.event_bus.subscribe(TOPIC_POSITION_UPDATED, self._on_position_update)
        self._render_all()

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(TOPIC_WALLET_UPDATED, self._on_wallet_update)
        self.service.event_bus.unsubscribe(TOPIC_POSITION_UPDATED, self._on_position_update)

    def _on_wallet_update(self, payload: dict) -> None:
        """Bus callback — MUST use call_from_thread (called from non-UI thread)."""
        dispatch_to_ui(self.app, self._render_all)

    def _on_position_update(self, payload: dict) -> None:
        """Bus callback — MUST use call_from_thread (called from non-UI thread)."""
        dispatch_to_ui(self.app, self._render_all)

    def _render_all(self) -> None:
        """Fetch snapshot + repopulate balance card + ledger table."""
        self._render_balance_card()
        self._render_ledger()

    def refresh_data(self) -> None:
        self._render_all()

    def action_refresh(self) -> None:
        """Manual refresh — rerender balance card + ledger from the DB.

        Bus subscriptions already update on trades / topup / withdraw;
        `r` is a manual lever for edge cases (external writer, suspected
        stale display).
        """
        self._render_all()

    def _price_lookup(self, market_id: str, side: str) -> float | None:
        from scanner.core.event_store import get_market
        m = get_market(market_id, self.service.db)
        if m is None or m.yes_price is None:
            return None
        if side == "yes":
            return m.yes_price if 0 < m.yes_price < 1 else None
        no_p = m.no_price or round(1 - m.yes_price, 4)
        return no_p if 0 < no_p < 1 else None

    def _render_balance_card(self) -> None:
        try:
            card = self.query_one("#balance-card", PolilyCard)
        except Exception:
            return

        snapshot = self.service.get_wallet_snapshot()
        positions = self.service.get_all_positions()
        ov = compute_wallet_overview(
            snapshot=snapshot, positions=positions,
            price_lookup=self._price_lookup,
        )

        # Remove existing KVRow / Static children (keep title Static)
        for child in list(card.query(KVRow)):
            child.remove()
        # Remove dynamic headline/metrics statics added previously
        for child in list(card.query(".wallet-dynamic")):
            child.remove()

        total_color = "green" if ov["total_pnl"] > 0 else "red" if ov["total_pnl"] < 0 else "dim"
        total_sign = "+" if ov["total_pnl"] > 0 else ""
        headline = (
            f"总资产 [bold]${ov['equity']:.2f}[/bold]"
            f"   ·   累计回报 "
            f"[{total_color}]{total_sign}${ov['total_pnl']:.2f} "
            f"({ov['roi_pct']:+.2f}%)[/{total_color}]"
        )

        real = ov["realized_pnl"]
        unreal = ov["unrealized_pnl"]
        real_color = "green" if real > 0 else "red" if real < 0 else "dim"
        unreal_color = "green" if unreal > 0 else "red" if unreal < 0 else "dim"
        real_sign = "+" if real > 0 else ""
        unreal_sign = "+" if unreal > 0 else ""

        card.mount(Static(headline, classes="wallet-dynamic"))
        card.mount(KVRow(label="余额", value=f"${ov['cash_usd']:.2f}"))
        card.mount(KVRow(label="可用", value=f"${ov['cash_usd']:.2f}"))
        card.mount(KVRow(
            label="持仓市值",
            value=f"${ov['positions_market_value']:.2f}   ({ov['open_positions_count']} 个持仓)",
        ))
        card.mount(KVRow(
            label="浮动盈亏",
            value=f"[{unreal_color}]{unreal_sign}${unreal:.2f}[/{unreal_color}]",
        ))
        card.mount(KVRow(
            label="累计已实现",
            value=f"[{real_color}]{real_sign}${real:.2f}[/{real_color}]",
        ))
        card.mount(Static(
            f"净投入 ${ov['net_inflow']:.2f}  =  "
            f"初始 ${ov['starting_balance']:.2f}  +  "
            f"充值 ${ov['topup_total']:.2f}  -  "
            f"提现 ${ov['withdraw_total']:.2f}",
            classes="wallet-dynamic",
        ))

    def _render_ledger(self) -> None:
        try:
            table = self.query_one("#wallet-table", DataTable)
        except Exception:
            return
        table.clear()
        txs = self.service.get_wallet_transactions(limit=50)
        if not txs:
            # DataTable has no native empty state; the ledger stays empty,
            # the headline shows $100 cash (fresh wallet) — self-explanatory.
            return
        for tx in txs:
            amt = tx["amount_usd"]
            amt_color = "green" if amt > 0 else "red" if amt < 0 else "dim"
            amt_sign = "+" if amt > 0 else ""
            amt_str = f"[{amt_color}]{amt_sign}${amt:.2f}[/{amt_color}]"
            desc = _format_tx_description(tx)
            table.add_row(
                _format_ts(tx["created_at"]),
                desc,
                amt_str,
                f"${tx['balance_after']:.2f}",
            )

    # --- Actions ----------------------------------------------------------

    def action_topup(self) -> None:
        from scanner.tui.views.wallet_modals import TopupModal
        self.app.push_screen(TopupModal(self.service), self._on_modal_dismissed)

    def action_withdraw(self) -> None:
        from scanner.tui.views.wallet_modals import WithdrawModal
        self.app.push_screen(WithdrawModal(self.service), self._on_modal_dismissed)

    def action_reset(self) -> None:
        self._on_reset_clicked()

    def _on_reset_clicked(self) -> None:
        from scanner.tui.views.wallet_modals import WalletResetModal
        self.app.push_screen(WalletResetModal(self.service), self._on_modal_dismissed)

    def _on_modal_dismissed(self, result) -> None:
        # Truthy = action actually happened. Cancel paths dismiss with None;
        # Reset modal dismisses with True; Topup/Withdraw with a positive float.
        if result:
            self.refresh_data()
            # Also nudge the sidebar counts since positions may have changed.
            import contextlib
            with contextlib.suppress(Exception):
                self.screen.refresh_sidebar_counts()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "reset-btn":
            self._on_reset_clicked()
