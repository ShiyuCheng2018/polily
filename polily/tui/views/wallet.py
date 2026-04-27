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

from polily.core.events import (
    TOPIC_LANGUAGE_CHANGED,
    TOPIC_POSITION_UPDATED,
    TOPIC_WALLET_UPDATED,
)
from polily.tui._dispatch import once_per_tick
from polily.tui.bindings import NAV_BINDINGS
from polily.tui.i18n import t
from polily.tui.icons import ICON_WALLET
from polily.tui.service import PolilyService
from polily.tui.views._wallet_overview import compute_wallet_overview
from polily.tui.widgets.kv_row import KVRow
from polily.tui.widgets.polily_card import PolilyCard
from polily.tui.widgets.polily_zone import PolilyZone

logger = logging.getLogger(__name__)


# Map ledger DB enum codes → catalog keys. Lookup the catalog at format
# time (not at module import) so language switches are reflected
# immediately. Unknown types fall through to the raw enum string.
_TX_TYPE_KEY = {
    "TOPUP": "wallet.txn.topup",
    "WITHDRAW": "wallet.txn.withdraw",
    "BUY": "wallet.txn.buy",
    "SELL": "wallet.txn.sell",
    "FEE": "wallet.txn.fee",
    "RESOLVE": "wallet.txn.resolve",
    "MIGRATION": "wallet.txn.migration",
}


def _format_tx_description(tx: dict) -> str:
    """Condense one wallet_transactions row into the description column."""
    tx_type = tx["type"]
    catalog_key = _TX_TYPE_KEY.get(tx_type)
    label = t(catalog_key) if catalog_key else tx_type
    # Topup / Withdraw / Migration — just the label + any notes.
    if tx_type in ("TOPUP", "WITHDRAW", "MIGRATION"):
        return label + (f"  {tx['notes']}" if tx.get("notes") else "")
    # Buy / Sell — add market + side + shares@price.
    if tx_type in ("BUY", "SELL"):
        side = (tx.get("side") or "").upper()
        shares = tx.get("shares")
        price = tx.get("price")
        market = tx.get("market_id") or "?"
        parts = [label, f"{market} {side}"]
        if shares is not None and price is not None:
            parts.append(t("wallet.txn.shares_at_price", shares=shares, price=price * 100))
        return "  ".join(parts)
    # Fee — pin to market+side for grouping with the trade.
    if tx_type == "FEE":
        side = (tx.get("side") or "").upper()
        market = tx.get("market_id") or "?"
        return f"{label} ({market} {side})"
    # Resolve — mirror buy/sell shape.
    if tx_type == "RESOLVE":
        side = (tx.get("side") or "").upper()
        market = tx.get("market_id") or "?"
        shares = tx.get("shares")
        if shares is not None:
            shares_str = t("wallet.txn.shares_only", shares=shares)
            return f"{label} {market} {side} {shares_str}"
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

    # NOTE: I18nFooter renders the visible label via t(f"binding.{action}"),
    # so the strings below are only fallbacks. Don't blank them out —
    # Textual's Binding.make_bindings sets show=False when description is "".
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

    def __init__(self, service: PolilyService) -> None:
        super().__init__()
        self.service = service

    def compose(self) -> ComposeResult:
        yield PolilyCard(title=f"{ICON_WALLET} {t('wallet.title.balance_overview')}", id="balance-card")
        yield PolilyZone(title=t("wallet.title.transactions"), id="ledger-zone")
        with Horizontal(id="action-row"):
            # v0.8.0: the redundant `[t] 充值   [w] 提现   [r] 重置`
            # hint Static was removed — the Footer already surfaces
            # every binding. Only the destructive red button remains
            # as the primary reset entry point.
            yield Button(t("wallet.button.reset"), id="reset-btn", variant="error", classes="bold")

    def on_mount(self) -> None:
        # --- Balance card: mount ONCE with stable IDs so `_render_balance_card`
        # can update in place via `.set_value()` / `.update()`. Remount-style
        # refresh would leave stale widgets behind because Textual's
        # `remove()` is deferred (see v0.8.0 bus-fix commit).
        card = self.query_one("#balance-card", PolilyCard)
        card.mount(Static("", id="wallet-headline", classes="wallet-dynamic"))
        card.mount(KVRow(id="wallet-cash", label=t("wallet.label.cash"), value="—"))
        card.mount(KVRow(id="wallet-available", label=t("wallet.label.available"), value="—"))
        card.mount(KVRow(id="wallet-positions-value", label=t("wallet.label.positions_value"), value="—"))
        card.mount(KVRow(id="wallet-unrealized", label=t("wallet.label.unrealized"), value="—"))
        card.mount(KVRow(id="wallet-realized", label=t("wallet.label.realized"), value="—"))
        card.mount(Static("", id="wallet-footnote", classes="wallet-dynamic"))

        # --- Ledger table
        ledger_zone = self.query_one("#ledger-zone", PolilyZone)
        table = DataTable(id="wallet-table")
        ledger_zone.mount(table)
        table.cursor_type = "row"
        table.add_columns(
            (t("wallet.col.time"), "time"),
            (t("wallet.col.desc"), "desc"),
            (t("wallet.col.amount"), "amount"),
            (t("wallet.col.balance"), "balance"),
        )

        # Subscribe to event bus topics
        self.service.event_bus.subscribe(TOPIC_WALLET_UPDATED, self._on_wallet_update)
        self.service.event_bus.subscribe(TOPIC_POSITION_UPDATED, self._on_position_update)
        self.service.event_bus.subscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)
        # Initial render bypasses @once_per_tick — callers expect
        # synchronous population by the time on_mount returns.
        type(self)._render_all.__wrapped__(self)

    def on_unmount(self) -> None:
        self.service.event_bus.unsubscribe(TOPIC_WALLET_UPDATED, self._on_wallet_update)
        self.service.event_bus.unsubscribe(TOPIC_POSITION_UPDATED, self._on_position_update)
        self.service.event_bus.unsubscribe(TOPIC_LANGUAGE_CHANGED, self._on_lang_changed)

    def _on_wallet_update(self, payload: dict) -> None:
        """Bus callback — refresh coalesced by @once_per_tick on _render_all."""
        self._render_all()

    def _on_position_update(self, payload: dict) -> None:
        """Bus callback — refresh coalesced by @once_per_tick on _render_all."""
        self._render_all()

    def _on_lang_changed(self, payload: dict) -> None:
        """Bus callback — language switched, re-fetch all i18n strings.

        Static labels mounted in on_mount (KVRow labels, table column headers,
        card/zone titles, action button) need explicit updates because they
        aren't re-evaluated by _render_all. Dynamic content (headline /
        footnote / ledger rows) is re-resolved on every _render_all call
        so it picks up the new language for free.
        """
        import contextlib
        with contextlib.suppress(Exception):
            # Card / zone titles
            self.query_one("#balance-card .polily-card-title", Static).update(
                f"{ICON_WALLET} {t('wallet.title.balance_overview')}",
            )
            self.query_one("#ledger-zone .polily-zone-title", Static).update(
                t("wallet.title.transactions"),
            )
            # KVRow labels — query the inner .kv-label static (KVRow exposes
            # set_value but not set_label; reaching into the child Static is
            # the minimal-touch alternative)
            kv_labels = {
                "#wallet-cash": "wallet.label.cash",
                "#wallet-available": "wallet.label.available",
                "#wallet-positions-value": "wallet.label.positions_value",
                "#wallet-unrealized": "wallet.label.unrealized",
                "#wallet-realized": "wallet.label.realized",
            }
            for kv_id, key in kv_labels.items():
                self.query_one(f"{kv_id} .kv-label", Static).update(t(key))
            # Action button
            self.query_one("#reset-btn", Button).label = t("wallet.button.reset")
            # Ledger table column headers — DataTable.columns is keyed by
            # column key (the second tuple element we passed in add_columns).
            table = self.query_one("#wallet-table", DataTable)
            col_keys = {
                "time": "wallet.col.time",
                "desc": "wallet.col.desc",
                "amount": "wallet.col.amount",
                "balance": "wallet.col.balance",
            }
            for col_key, cat_key in col_keys.items():
                if col_key in table.columns:
                    table.columns[col_key].label = t(cat_key)
            # Force header repaint
            table.refresh()
        self._render_all()

    @once_per_tick
    def _render_all(self) -> None:
        """Fetch snapshot + repopulate balance card + ledger table.

        `@once_per_tick`: subscribes to WALLET+POSITION — heartbeat
        fan-out would otherwise trigger 2× per tick.
        """
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
        from polily.core.event_store import get_market
        m = get_market(market_id, self.service.db)
        if m is None or m.yes_price is None:
            return None
        if side == "yes":
            return m.yes_price if 0 < m.yes_price < 1 else None
        no_p = m.no_price or round(1 - m.yes_price, 4)
        return no_p if 0 < no_p < 1 else None

    def _render_balance_card(self) -> None:
        """Update the 7 balance-card widgets in place.

        Widgets are mounted once in `on_mount` with stable IDs
        (`#wallet-headline`, `#wallet-cash`, `#wallet-available`,
        `#wallet-positions-value`, `#wallet-unrealized`,
        `#wallet-realized`, `#wallet-footnote`). Updating in place
        avoids the remove+remount race where Textual's deferred
        `remove()` could leave duplicate KVRows briefly visible under
        rapid bus callbacks.
        """
        snapshot = self.service.get_wallet_snapshot()
        positions = self.service.get_all_positions()
        ov = compute_wallet_overview(
            snapshot=snapshot, positions=positions,
            price_lookup=self._price_lookup,
        )

        total_color = "green" if ov["total_pnl"] > 0 else "red" if ov["total_pnl"] < 0 else "dim"
        total_sign = "+" if ov["total_pnl"] > 0 else ""
        headline = (
            f"{t('wallet.headline.equity')} [bold]${ov['equity']:.2f}[/bold]"
            f"   ·   {t('wallet.headline.total_return')} "
            f"[{total_color}]{total_sign}${ov['total_pnl']:.2f} "
            f"({ov['roi_pct']:+.2f}%)[/{total_color}]"
        )

        real = ov["realized_pnl"]
        unreal = ov["unrealized_pnl"]
        real_color = "green" if real > 0 else "red" if real < 0 else "dim"
        unreal_color = "green" if unreal > 0 else "red" if unreal < 0 else "dim"
        real_sign = "+" if real > 0 else ""
        unreal_sign = "+" if unreal > 0 else ""

        footnote = (
            f"{t('wallet.footnote.net_inflow')} ${ov['net_inflow']:.2f}  =  "
            f"{t('wallet.footnote.starting')} ${ov['starting_balance']:.2f}  +  "
            f"{t('wallet.footnote.topup')} ${ov['topup_total']:.2f}  -  "
            f"{t('wallet.footnote.withdraw')} ${ov['withdraw_total']:.2f}"
        )

        try:
            self.query_one("#wallet-headline", Static).update(headline)
            self.query_one("#wallet-cash", KVRow).set_value(f"${ov['cash_usd']:.2f}")
            self.query_one("#wallet-available", KVRow).set_value(f"${ov['cash_usd']:.2f}")
            self.query_one("#wallet-positions-value", KVRow).set_value(
                f"${ov['positions_market_value']:.2f}   "
                f"({t('wallet.positions_count', count=ov['open_positions_count'])})",
            )
            self.query_one("#wallet-unrealized", KVRow).set_value(
                f"[{unreal_color}]{unreal_sign}${unreal:.2f}[/{unreal_color}]",
            )
            self.query_one("#wallet-realized", KVRow).set_value(
                f"[{real_color}]{real_sign}${real:.2f}[/{real_color}]",
            )
            self.query_one("#wallet-footnote", Static).update(footnote)
        except Exception:
            # Card children aren't mounted yet — on_mount will retry after
            # mounting. Safe to no-op here.
            return

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
        from polily.tui.views.wallet_modals import TopupModal
        self.app.push_screen(TopupModal(self.service), self._on_modal_dismissed)

    def action_withdraw(self) -> None:
        from polily.tui.views.wallet_modals import WithdrawModal
        self.app.push_screen(WithdrawModal(self.service), self._on_modal_dismissed)

    def action_reset(self) -> None:
        self._on_reset_clicked()

    def _on_reset_clicked(self) -> None:
        from polily.tui.views.wallet_modals import WalletResetModal
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
