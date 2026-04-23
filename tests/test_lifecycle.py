"""Unit tests for polily.core.lifecycle — state derivation + labels."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from polily.core.lifecycle import (
    EventState,
    MarketState,
    event_state,
    event_state_label,
    market_state,
    market_state_label,
    settled_winner_suffix,
)


def test_market_state_enum_values():
    assert MarketState.TRADING.value == "trading"
    assert MarketState.PENDING_SETTLEMENT.value == "pending_settlement"
    assert MarketState.SETTLING.value == "settling"
    assert MarketState.SETTLED.value == "settled"


def test_event_state_enum_values():
    assert EventState.ACTIVE.value == "active"
    assert EventState.AWAITING_FULL_SETTLEMENT.value == "awaiting_full_settlement"
    assert EventState.RESOLVED.value == "resolved"


def test_market_state_labels_chinese():
    assert market_state_label(MarketState.TRADING) == "交易中"
    assert market_state_label(MarketState.PENDING_SETTLEMENT) == "即将结算"
    assert market_state_label(MarketState.SETTLING) == "结算中"
    assert market_state_label(MarketState.SETTLED) == "已结算"


def test_event_state_labels_chinese():
    assert event_state_label(EventState.ACTIVE) == "进行中"
    assert event_state_label(EventState.AWAITING_FULL_SETTLEMENT) == "待全部结算"
    assert event_state_label(EventState.RESOLVED) == "已结算"


def test_settled_winner_suffix_yes():
    m = MagicMock()
    m.resolved_outcome = "yes"
    assert settled_winner_suffix(m) == " YES 获胜"


def test_settled_winner_suffix_no():
    m = MagicMock()
    m.resolved_outcome = "no"
    assert settled_winner_suffix(m) == " NO 获胜"


def test_settled_winner_suffix_split():
    m = MagicMock()
    m.resolved_outcome = "split"
    assert settled_winner_suffix(m) == " 平局"


def test_settled_winner_suffix_none():
    """resolved_outcome=None → empty string (caller shows plain label)."""
    m = MagicMock()
    m.resolved_outcome = None
    assert settled_winner_suffix(m) == ""


def test_settled_winner_suffix_void():
    """resolved_outcome='void' → ' 市场作废' (market was canceled)."""
    m = MagicMock()
    m.resolved_outcome = "void"
    assert settled_winner_suffix(m) == " 市场作废"


def test_every_market_state_has_label():
    """Every MarketState enum value must have a label mapping."""
    for state in MarketState:
        assert market_state_label(state)  # non-empty


def test_every_event_state_has_label():
    """Every EventState enum value must have a label mapping."""
    for state in EventState:
        assert event_state_label(state)  # non-empty


def _mk_market(*, closed=0, end_date=None, resolved_outcome=None):
    """Build a MarketRow-like object with the fields lifecycle inspects."""
    m = MagicMock()
    m.closed = closed
    m.end_date = end_date
    m.resolved_outcome = resolved_outcome
    return m


def test_market_state_trading():
    now = datetime(2026, 4, 22, 0, 0, tzinfo=UTC)
    future = (now + timedelta(days=7)).isoformat()
    m = _mk_market(closed=0, end_date=future)
    assert market_state(m, now=now) == MarketState.TRADING


def test_market_state_trading_null_end_date():
    """closed=0 AND end_date=None → TRADING (pre-scheduled market, not expired)."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=0, end_date=None)
    assert market_state(m, now=now) == MarketState.TRADING


def test_market_state_pending_settlement_past_end_date():
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    past = (now - timedelta(hours=12)).isoformat()
    m = _mk_market(closed=0, end_date=past)
    assert market_state(m, now=now) == MarketState.PENDING_SETTLEMENT


def test_market_state_settling_closed_no_outcome():
    """closed=1 AND resolved_outcome=None → SETTLING (UMA window)."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome=None)
    assert market_state(m, now=now) == MarketState.SETTLING


def test_market_state_settled_with_outcome():
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome="no")
    assert market_state(m, now=now) == MarketState.SETTLED


def test_market_state_settled_with_split():
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome="split")
    assert market_state(m, now=now) == MarketState.SETTLED


def test_market_state_boundary_end_date_equals_now():
    """end_date == now → PENDING_SETTLEMENT (≤ semantics)."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=0, end_date=now.isoformat())
    assert market_state(m, now=now) == MarketState.PENDING_SETTLEMENT


def test_market_state_closed_none_treated_as_trading():
    """closed=None (edge-case defensive: int(None or 0) == 0) → falls through to time-based branch."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=1)).isoformat()
    m = _mk_market(closed=None, end_date=future)
    assert market_state(m, now=now) == MarketState.TRADING


def test_market_state_naive_iso_treated_as_utc():
    """ISO string without timezone info is assumed UTC."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    # Naive ISO (no +00:00) for a future time
    future_naive = (now + timedelta(days=1)).replace(tzinfo=None).isoformat()
    m = _mk_market(closed=0, end_date=future_naive)
    assert market_state(m, now=now) == MarketState.TRADING


def test_market_state_malformed_end_date_falls_back_to_trading():
    """Unparseable end_date → safe fallback TRADING (Gamma schema drift guard)."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=0, end_date="not-a-date")
    assert market_state(m, now=now) == MarketState.TRADING


def _mk_event(*, closed=0):
    """Build an EventRow-like object with the fields lifecycle inspects."""
    e = MagicMock()
    e.closed = closed
    return e


def test_event_state_no_markets_is_active():
    """Empty markets list on an open event → ACTIVE (pre-scoring edge case)."""
    e = _mk_event(closed=0)
    assert event_state(e, []) == EventState.ACTIVE


def test_event_state_all_trading_is_active():
    """At least one child in TRADING → ACTIVE."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=7)).isoformat()
    markets = [_mk_market(closed=0, end_date=future) for _ in range(3)]
    assert event_state(_mk_event(closed=0), markets, now=now) == EventState.ACTIVE


def test_event_state_mixed_trading_and_settled_still_active():
    """Any TRADING child → ACTIVE, regardless of other states."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=7)).isoformat()
    past = (now - timedelta(days=1)).isoformat()
    markets = [
        _mk_market(closed=0, end_date=future),                    # TRADING
        _mk_market(closed=1, resolved_outcome="no"),              # SETTLED
        _mk_market(closed=0, end_date=past),                      # PENDING_SETTLEMENT
    ]
    assert event_state(_mk_event(closed=0), markets, now=now) == EventState.ACTIVE


def test_event_state_awaiting_full_settlement():
    """No TRADING children + event.closed=0 → AWAITING_FULL_SETTLEMENT."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    past = (now - timedelta(days=1)).isoformat()
    markets = [
        _mk_market(closed=0, end_date=past),                      # PENDING_SETTLEMENT
        _mk_market(closed=1, resolved_outcome=None),              # SETTLING
        _mk_market(closed=1, resolved_outcome="yes"),             # SETTLED
    ]
    assert event_state(_mk_event(closed=0), markets, now=now) == EventState.AWAITING_FULL_SETTLEMENT


def test_event_state_resolved_when_event_closed():
    """event.closed=1 is terminal, regardless of child states."""
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    markets = [_mk_market(closed=1, resolved_outcome="no") for _ in range(4)]
    assert event_state(_mk_event(closed=1), markets, now=now) == EventState.RESOLVED
