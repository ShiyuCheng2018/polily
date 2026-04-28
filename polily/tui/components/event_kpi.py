"""EventKpiRow: KPI metric cards for event overview."""

import contextlib
import re

from textual.app import ComposeResult
from textual.containers import HorizontalGroup
from textual.widget import Widget

from polily.tui.i18n import t
from polily.tui.widgets.cards import MetricCard


def _subcount_label(markets: list) -> str:
    """子市场 card content — plain total count.

    Closed / settlement breakdown now lives in the '市场' PolilyZone title
    (see _market_zone_title_suffix in event_detail.py), so this card stays
    a single number.
    """
    return str(len(markets))


def _kpi_end_label(event, markets: list, *, now=None) -> str:
    """kpi-end MetricCard content — event state aware.

    ACTIVE                                    → format_countdown_range
                                                over TRADING children
    AWAITING_FULL_SETTLEMENT / RESOLVED       → translated event-state label
    """
    from polily.core.lifecycle import EventState, MarketState, event_state, market_state
    from polily.tui.lifecycle_labels import event_state_label_i18n

    state = event_state(event, markets, now=now)
    if state in (EventState.RESOLVED, EventState.AWAITING_FULL_SETTLEMENT):
        return event_state_label_i18n(state)

    # ACTIVE: range only over TRADING children. Filtering by lifecycle
    # state (not `closed=0`) excludes PENDING_SETTLEMENT markets whose
    # end_date is already in the past — those would render as "已过期"
    # inside format_countdown_range and leak the old expired-label wording
    # into the new lifecycle UI.
    from polily.tui.utils import format_countdown_range
    ends = [
        m.end_date for m in markets
        if m.end_date and market_state(m, now=now) == MarketState.TRADING
    ]
    if not ends:
        return "?"
    return format_countdown_range(min(ends), max(ends))


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
                    yield self._make_card("kpi-overround", t("kpi.card.overround"))
                else:
                    yield self._make_card("kpi-overround", t("kpi.card.min_spread"))
                yield self._make_card("kpi-count", t("kpi.card.subcount"))
                yield self._make_card("kpi-end", t("kpi.card.settlement"))
                yield self._make_card("kpi-score", t("kpi.card.score"))
            else:
                yield self._make_card("kpi-yes", "YES")
                yield self._make_card("kpi-no", "NO")
                yield self._make_card("kpi-spread", t("kpi.card.spread"))
                yield self._make_card("kpi-score", t("kpi.card.score"))

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

        self._set_card("kpi-yes", f"{yes * 100:.1f}¢")
        self._set_card("kpi-no", f"{no * 100:.1f}¢")
        self._set_card("kpi-spread", f"{spread * 100:.1f}¢" if spread else "?")

        score = event.structure_score
        mkt_summary = self._market_score_summary(markets)
        score_text = t("kpi.event_score", score=score) if score else "?"
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
                self._set_card(
                    "kpi-overround",
                    f"{sign}{overround:.1%}\n{t('kpi.overround_net_prefix')}{net_sign}{net * 100:.1f}¢",
                )
            else:
                self._set_card("kpi-overround", "?")
        else:
            spreads = [
                m.spread for m in active
                if m.spread is not None and m.spread > 0
                and m.yes_price is not None and 0.05 <= m.yes_price <= 0.95
            ]
            if spreads:
                self._set_card("kpi-overround", f"{min(spreads) * 100:.1f}¢")
            else:
                self._set_card("kpi-overround", "?")

        self._set_card("kpi-count", _subcount_label(markets))

        self._set_card("kpi-end", _kpi_end_label(event, markets))

        score = event.structure_score
        mkt_summary = self._market_score_summary(markets)
        score_text = t("kpi.event_score", score=score) if score else "?"
        if mkt_summary:
            score_text += f"\n{mkt_summary}"
        self._set_card("kpi-score", score_text)

    @staticmethod
    def _leader_card_label(event, markets) -> str:
        if event.neg_risk:
            return t("kpi.leader.leader")
        title = event.title or ""
        if re.search(r'\b(above|below|exceed|reach)\b', title, re.I):
            return t("kpi.leader.watch_zone")
        if re.search(r'\bby\b', title, re.I) or re.search(r'ends?\s+by', title, re.I):
            return t("kpi.leader.recent_window")
        return t("kpi.leader.most_likely")

    def _fill_leader_neg_risk(self, active) -> None:
        leader = max(active, key=lambda m: m.yes_price or 0, default=None)
        if leader and leader.yes_price is not None:
            name = (leader.group_item_title or leader.question)[:20]
            no = leader.no_price if leader.no_price is not None else round(1 - leader.yes_price, 4)
            self._set_card("kpi-leader", f"{name}\nYES:{leader.yes_price * 100:.1f}¢ NO:{no * 100:.1f}¢")
        else:
            self._set_card("kpi-leader", "?")

    def _fill_leader_independent(self, active) -> None:
        tradeable = [m for m in active if m.yes_price and 0.05 <= m.yes_price <= 0.95]
        if tradeable:
            tradeable.sort(key=lambda m: abs(m.yes_price - 0.5))
            best = tradeable[0]
            name = (best.group_item_title or best.question)[:20]
            self._set_card("kpi-leader", f"{name}\nYES:{best.yes_price * 100:.1f}¢ NO:{best.no_price * 100:.1f}¢")
        else:
            self._set_card("kpi-leader", t("kpi.leader.no_tradable"))

    @staticmethod
    def _market_score_summary(markets) -> str:
        scores = [m.structure_score for m in markets if m.structure_score is not None and not m.closed]
        if not scores:
            return ""
        avg = sum(scores) / len(scores)
        return t("kpi.market_score", avg=avg, lo=min(scores), hi=max(scores))

    @staticmethod
    def _make_card(card_id: str, title: str) -> MetricCard:
        card = MetricCard(id=card_id)
        card.border_title = title
        return card

    def _set_card(self, card_id: str, content: str) -> None:
        with contextlib.suppress(Exception):
            self.query_one(f"#{card_id}", MetricCard).update(content)
