"""PositionPanel: paper trade positions with visual P&L cards.

v0.8.0: Removed inner DashPanel wrapper — the outer PolilyZone
(event_detail.py line 142) already provides the "持仓" section border +
title, so nesting a DashPanel with the same title inside was redundant.
Cards now render directly inside the zone; each pos-card keeps its
accent border to distinguish individual positions.
"""
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from polily.pnl import calc_unrealized_pnl


class PositionPanel(Widget):
    """Shows paper trade positions with price bars and P&L."""

    DEFAULT_CSS = """
    PositionPanel { height: auto; }
    PositionPanel .pos-card { border: tall $accent; padding: 0 1; margin: 1 1; height: auto; }
    PositionPanel .pos-row { padding: 0 0 0 1; }
    PositionPanel .pos-summary { padding: 1 0 0 1; text-style: bold; }
    PositionPanel .pos-empty { padding: 0 0 0 1; }
    """

    def __init__(self, trades: list, markets: list, movements: list | None = None):
        super().__init__()
        self._trades = trades
        self._markets = markets
        self._movements = movements or []

    def compose(self) -> ComposeResult:
        if not self._trades:
            yield Static("[dim]无持仓 — 按 t 建仓[/dim]", classes="pos-empty")
            return

        markets_by_id = {m.market_id: m for m in self._markets if hasattr(m, "market_id")}
        total_cost = 0.0
        total_value = 0.0
        total_pnl = 0.0

        for _i, t in enumerate(self._trades):
            side = t.get("side", "?")
            entry = t.get("entry_price", 0)
            size = t.get("position_size_usd", 0)
            title = (t.get("title") or "?")[:25]
            market_id = t.get("market_id", "")
            shares = size / entry if entry > 0 else 0

            total_cost += size

            mr = markets_by_id.get(market_id)
            current_yes = mr.yes_price if mr and mr.yes_price is not None else None
            current_price = None
            pnl = 0.0
            pnl_pct = 0.0

            if current_yes is not None and entry > 0:
                current_price = current_yes if side == "yes" else round(1 - current_yes, 4)
                pnl_data = calc_unrealized_pnl(side, entry, current_yes, size)
                pnl = pnl_data["pnl"]
                pnl_pct = pnl / size * 100 if size > 0 else 0
                total_value += shares * current_price
                total_pnl += pnl

            side_display = side.upper()

            pnl_str = ""
            if current_price is not None:
                color = "green" if pnl >= 0 else "red"
                sign = "+" if pnl >= 0 else ""
                pnl_str = f"  |  入场 @ {entry * 100:.1f}¢  [{color}]{sign}${pnl:.2f} ({sign}{pnl_pct:.1f}%)[/{color}]"

            with Vertical(classes="pos-card"):
                yield Static(
                    f"[bold]{title}[/]  {side_display} @ {current_price * 100:.1f}¢  ${size:.0f} ({shares:.0f}股){pnl_str}" if current_price is not None
                    else f"[bold]{title}[/]  {side_display} @ {entry * 100:.1f}¢  ${size:.0f} ({shares:.0f}股)",
                    classes="pos-row",
                )

        if len(self._trades) > 0:
            pnl_color = "green" if total_pnl >= 0 else "red"
            pnl_sign = "+" if total_pnl >= 0 else ""
            yield Static(
                f"合计 ${total_value:.2f}  [{pnl_color}]{pnl_sign}${total_pnl:.2f}[/{pnl_color}]",
                classes="pos-summary",
            )
