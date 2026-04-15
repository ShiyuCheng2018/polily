"""PositionPanel: paper trade positions with P&L."""

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

from scanner.pnl import calc_unrealized_pnl
from scanner.tui.widgets.cards import DashPanel


class PositionPanel(Widget):
    """Shows paper trade positions and unrealized P&L."""

    DEFAULT_CSS = """
    PositionPanel { height: auto; }
    PositionPanel DashPanel { width: 1fr; margin: 0 1; height: auto; }
    PositionPanel .row { padding: 0 0 0 1; }
    """

    def __init__(self, trades: list, markets: list, movements: list | None = None):
        super().__init__()
        self._trades = trades
        self._markets = markets
        self._movements = movements or []

    def compose(self) -> ComposeResult:
        panel = DashPanel(id="panel-position")
        panel.border_title = "持仓"
        with panel:
            if not self._trades:
                yield Static("[dim]无持仓[/dim]", classes="row")
                return

            for t in self._trades:
                side = t.get("side", "?").upper()
                entry = t.get("entry_price", 0)
                size = t.get("position_size_usd", 0)
                title = (t.get("title") or "")[:30]
                yield Static(f"{side} @ {entry:.2f}  ${size:.0f}  {title}", classes="row")

                mid = t.get("market_id", "")
                current_mr = next((m for m in self._markets if m.market_id == mid), None)
                if current_mr and current_mr.yes_price is not None and entry > 0:
                    pnl_data = calc_unrealized_pnl(side.lower(), entry, current_mr.yes_price, size)
                    unrealized = pnl_data["pnl"]
                    color = "green" if unrealized >= 0 else "red"
                    yield Static(f"  [{color}]P&L: {unrealized:+.2f}[/{color}]", classes="row")

            if self._movements:
                yield Static("")
                latest = self._movements[0]
                mag = latest.get("magnitude", 0)
                qual = latest.get("quality", 0)
                label = latest.get("label", "")
                yield Static(f"[dim]最近异动: M={mag:.0f} Q={qual:.0f} {label}[/dim]", classes="row")
