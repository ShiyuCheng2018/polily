"""EventKpiRow: KPI metric cards for event overview."""

import contextlib
import re
from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.widget import Widget

from scanner.tui.widgets.cards import MetricCard


class EventKpiRow(Widget):
    """KPI card row — adapts layout for binary vs multi-outcome events."""

    DEFAULT_CSS = """
    EventKpiRow { height: auto; }
    EventKpiRow #kpi-row { height: auto; min-height: 5; padding: 0; }
    EventKpiRow #kpi-row MetricCard { height: 5; margin: 0 1; }
    """

    def __init__(self, event, markets: list):
        super().__init__()
        self._event = event
        self._markets = markets

    def compose(self) -> ComposeResult:
        event = self._event
        markets = self._markets
        is_multi = len(markets) > 1

        with HorizontalGroup(id="kpi-row"):
            if is_multi:
                leader_label = self._leader_card_label(event, markets)
                yield self._make_card("kpi-leader", leader_label)
                if event.neg_risk:
                    yield self._make_card("kpi-overround", "溢价率")
                else:
                    yield self._make_card("kpi-overround", "最小价差")
                yield self._make_card("kpi-count", "子市场")
                yield self._make_card("kpi-end", "结算")
                yield self._make_card("kpi-score", "评分")
            else:
                yield self._make_card("kpi-yes", "YES")
                yield self._make_card("kpi-no", "NO")
                yield self._make_card("kpi-spread", "价差")
                yield self._make_card("kpi-score", "评分")

    def on_mount(self) -> None:
        self._fill_kpi()

    def _fill_kpi(self) -> None:
        event = self._event
        markets = self._markets
        if not event:
            return
        if len(markets) > 1:
            self._fill_kpi_multi(event, markets)
        else:
            self._fill_kpi_binary(event, markets)

    def _fill_kpi_binary(self, event, markets) -> None:
        mr = markets[0] if markets else None
        yes = mr.yes_price if mr and mr.yes_price is not None else 0
        no = mr.no_price if mr and mr.no_price is not None else round(1 - yes, 4)
        spread = mr.spread if mr and mr.spread else None

        self._set_card("kpi-yes", f"{yes:.3f}")
        self._set_card("kpi-no", f"{no:.3f}")
        self._set_card("kpi-spread", f"{spread:.1%}" if spread else "?")

        score = event.structure_score
        mkt_summary = self._market_score_summary(markets)
        score_text = f"事件 {score:.0f}" if score else "?"
        if mkt_summary:
            score_text += f"\n{mkt_summary}"
        self._set_card("kpi-score", score_text)

    def _fill_kpi_multi(self, event, markets) -> None:
        active = [m for m in markets if not m.closed and m.yes_price is not None]

        if event.neg_risk:
            self._fill_leader_neg_risk(active)
        else:
            self._fill_leader_independent(active)

        if event.neg_risk:
            prices = [m.yes_price for m in active if m.yes_price is not None]
            if prices:
                overround = sum(prices) - 1.0
                total_spread = sum(m.spread for m in active if m.spread is not None)
                net = overround + total_spread
                sign = "+" if overround >= 0 else ""
                net_sign = "+" if net >= 0 else ""
                self._set_card("kpi-overround", f"{sign}{overround:.1%}\n净{net_sign}{net:.1%}")
            else:
                self._set_card("kpi-overround", "?")
        else:
            spreads = [
                m.spread for m in active
                if m.spread is not None and m.spread > 0
                and m.yes_price is not None and 0.05 <= m.yes_price <= 0.95
            ]
            if spreads:
                self._set_card("kpi-overround", f"{min(spreads):.1%}")
            else:
                self._set_card("kpi-overround", "?")

        closed_count = sum(1 for m in markets if m.closed)
        count_str = str(len(markets))
        if closed_count > 0:
            count_str += f" ({closed_count}过期)"
        self._set_card("kpi-count", count_str)

        from scanner.tui.utils import format_countdown_range
        now_iso = datetime.now(UTC).isoformat()
        active_ends = [m.end_date for m in markets if not m.closed and m.end_date and m.end_date > now_iso]
        if active_ends:
            self._set_card("kpi-end", format_countdown_range(min(active_ends), max(active_ends)))
        else:
            self._set_card("kpi-end", "?")

        score = event.structure_score
        mkt_summary = self._market_score_summary(markets)
        score_text = f"事件 {score:.0f}" if score else "?"
        if mkt_summary:
            score_text += f"\n{mkt_summary}"
        self._set_card("kpi-score", score_text)

    @staticmethod
    def _leader_card_label(event, markets) -> str:
        if event.neg_risk:
            return "领先"
        title = event.title or ""
        if re.search(r'\b(above|below|exceed|reach)\b', title, re.I):
            return "关注区"
        if re.search(r'\bby\b', title, re.I) or re.search(r'ends?\s+by', title, re.I):
            return "最近窗口"
        return "最高概率"

    def _fill_leader_neg_risk(self, active) -> None:
        leader = max(active, key=lambda m: m.yes_price or 0, default=None)
        if leader and leader.yes_price is not None:
            name = (leader.group_item_title or leader.question)[:20]
            no = leader.no_price if leader.no_price is not None else round(1 - leader.yes_price, 4)
            self._set_card("kpi-leader", f"{name}\nYES:{leader.yes_price:.2f} NO:{no:.2f}")
        else:
            self._set_card("kpi-leader", "?")

    def _fill_leader_independent(self, active) -> None:
        tradeable = [m for m in active if m.yes_price and 0.05 <= m.yes_price <= 0.95]
        if tradeable:
            tradeable.sort(key=lambda m: abs(m.yes_price - 0.5))
            best = tradeable[0]
            name = (best.group_item_title or best.question)[:20]
            self._set_card("kpi-leader", f"{name}\nYES:{best.yes_price:.2f} NO:{best.no_price:.2f}")
        else:
            self._set_card("kpi-leader", "无可交易标的")

    @staticmethod
    def _market_score_summary(markets) -> str:
        scores = [m.structure_score for m in markets if m.structure_score is not None and not m.closed]
        if not scores:
            return ""
        avg = sum(scores) / len(scores)
        return f"市场 {avg:.0f} ({min(scores):.0f}~{max(scores):.0f})"

    @staticmethod
    def _make_card(card_id: str, title: str) -> MetricCard:
        card = MetricCard(id=card_id)
        card.border_title = title
        return card

    def _set_card(self, card_id: str, content: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(f"#{card_id}", MetricCard).update(content)
