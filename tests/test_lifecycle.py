"""Unit tests for scanner.core.lifecycle — state derivation + labels."""

from unittest.mock import MagicMock

from scanner.core.lifecycle import (
    EventState,
    MarketState,
    event_state_label,
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
    m = MagicMock(); m.resolved_outcome = "yes"
    assert settled_winner_suffix(m) == " YES 获胜"


def test_settled_winner_suffix_no():
    m = MagicMock(); m.resolved_outcome = "no"
    assert settled_winner_suffix(m) == " NO 获胜"


def test_settled_winner_suffix_split():
    m = MagicMock(); m.resolved_outcome = "split"
    assert settled_winner_suffix(m) == " 平局"


def test_settled_winner_suffix_none():
    """resolved_outcome=None → empty string (caller shows plain label)."""
    m = MagicMock(); m.resolved_outcome = None
    assert settled_winner_suffix(m) == ""


def test_settled_winner_suffix_void():
    """resolved_outcome='void' → ' 市场作废' (market was canceled)."""
    m = MagicMock(); m.resolved_outcome = "void"
    assert settled_winner_suffix(m) == " 市场作废"


def test_every_market_state_has_label():
    """Every MarketState enum value must have a label mapping."""
    for state in MarketState:
        assert market_state_label(state)  # non-empty


def test_every_event_state_has_label():
    """Every EventState enum value must have a label mapping."""
    for state in EventState:
        assert event_state_label(state)  # non-empty
