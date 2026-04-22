"""SubMarketTable: expandable sub-market table with score breakdowns."""

import contextlib
import json as _json
from datetime import datetime

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static

from scanner.core.lifecycle import MarketState, market_state, market_state_label


def _settlement_cell_text(market, *, now: datetime | None = None) -> str:
    """Render the '结算' column cell for a sub-market.

    TRADING → countdown string (e.g. '04-25 10:00 (3天0小时)').
    Non-TRADING → bracketed state label (e.g. '[即将结算]').

    Column is narrow so SETTLED does NOT include winner suffix — that
    lives in the '市场' zone title (single market) or the breadcrumb.
    """
    state = market_state(market, now=now)
    if state == MarketState.TRADING:
        from scanner.tui.utils import format_countdown
        return format_countdown(market.end_date) if market.end_date else "?"
    return f"[{market_state_label(state)}]"


class SubMarketTable(Widget):
    """Multi-outcome sub-market table with expandable score breakdowns."""

    DEFAULT_CSS = """
    SubMarketTable { height: auto; max-height: 14; margin: 0 1; }
    """

    def __init__(self, markets: list, event=None):
        super().__init__()
        self._markets = markets
        self._event = event
        self._expanded: set[str] = set()
        self._row_map: list[dict] = []

    def compose(self) -> ComposeResult:
        if len(self._markets) <= 1:
            return
        yield Static("")
        table = DataTable(id="sub-market-table")
        table.cursor_type = "row"
        table.add_columns("选项", "YES", "NO", "价差", "成交量", "结算", "评分")
        yield table

    def on_mount(self) -> None:
        if len(self._markets) > 1:
            self._rebuild()

    def _rebuild(self) -> None:
        try:
            table = self.query_one("#sub-market-table", DataTable)
        except Exception:
            return

        table.clear()
        self._row_map = []

        for mr in self._markets:
            label = mr.group_item_title or mr.question[:40]
            is_expanded = mr.market_id in self._expanded
            prefix = "▼ " if is_expanded else "▶ " if not mr.closed else "  "

            yes = f"{mr.yes_price * 100:.1f}¢" if mr.yes_price is not None else "?"
            no = f"{mr.no_price * 100:.1f}¢" if mr.no_price is not None else "?"
            spread = f"{mr.spread * 100:.1f}¢" if mr.spread else "?"
            vol = f"${mr.volume:,.0f}" if mr.volume else "?"
            end = _settlement_cell_text(mr)

            score_str = "?"
            if mr.structure_score:
                overall = ""
                if mr.score_breakdown:
                    with contextlib.suppress(ValueError, TypeError):
                        bd = _json.loads(mr.score_breakdown)
                        overall = bd.get("commentary", {}).get("overall", "")
                score_str = f"{mr.structure_score:.0f} {overall}" if overall else f"{mr.structure_score:.0f}"
            table.add_row(f"{prefix}{label}", yes, no, spread, vol, end, score_str, key=f"m_{mr.market_id}")
            self._row_map.append({"type": "market", "market": mr})

            if is_expanded:
                self._add_breakdown_rows(table, mr)

    def _add_breakdown_rows(self, table: DataTable, mr) -> None:
        bd = None
        if mr.score_breakdown:
            with contextlib.suppress(ValueError, TypeError):
                bd = _json.loads(mr.score_breakdown)

        from scanner.scan.scoring import _DEFAULT_WEIGHTS, _TYPE_WEIGHTS
        mtype = getattr(mr, "market_type", None) or "other"
        if mtype == "other" and self._event:
            mtype = getattr(self._event, "market_type", None) or "other"
        tw = _TYPE_WEIGHTS.get(mtype, _DEFAULT_WEIGHTS)

        if bd:
            breakdown = [
                ("流动性", bd.get("liquidity", 0), tw["liquidity"]),
                ("可验证性", bd.get("verifiability", 0), tw["verifiability"]),
                ("概率空间", bd.get("probability", 0), tw["probability"]),
                ("时间", bd.get("time", 0), tw["time"]),
                ("摩擦", bd.get("friction", 0), tw["friction"]),
            ]
            if tw.get("net_edge", 0) > 0:
                breakdown.append(("Edge", bd.get("net_edge", 0), tw["net_edge"]))
        else:
            breakdown = []

        dim_keys = ["liquidity", "verifiability", "probability", "time", "friction"]
        if tw.get("net_edge", 0) > 0:
            dim_keys.append("net_edge")

        for i, (name, val, max_val) in enumerate(breakdown):
            val = min(val, max_val) if max_val > 0 else val
            bar_len = int(val / max_val * 15) if max_val > 0 else 0
            bar = "█" * bar_len + "░" * (15 - bar_len)
            comment = ""
            if bd and i < len(dim_keys):
                comment = bd.get("commentary", {}).get("dim_comments", {}).get(dim_keys[i], "")
            connector = "└" if i == len(breakdown) - 1 else "├"
            table.add_row(
                f"  {connector} {name}", f"{bar} {val:.0f}/{max_val}", comment, "", "", "", "",
                key=f"bd_{mr.market_id}_{i}",
            )
            self._row_map.append({"type": "breakdown", "market_id": mr.market_id})

        # Total score row removed — already shown in the 评分 column

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "sub-market-table":
            return
        row_idx = event.cursor_row
        if row_idx < 0 or row_idx >= len(self._row_map):
            return
        item = self._row_map[row_idx]
        if item["type"] == "market":
            mr = item["market"]
            if mr.closed:
                return
            mid = mr.market_id
            if mid in self._expanded:
                self._expanded.discard(mid)
            else:
                self._expanded.add(mid)
            self._rebuild()
