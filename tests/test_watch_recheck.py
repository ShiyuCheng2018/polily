"""Tests for watch recheck orchestration."""

import pytest

from scanner.market_state import MarketState, get_market_state, set_market_state
from scanner.watch_recheck import recheck_market


def test_recheck_expired_market_closes(polily_db):
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-03-30T10:00:00",
        title="Expired Market",
        resolution_time="2026-03-31T00:00:00+00:00",
        price_at_watch=0.65,
    ), polily_db)
    result = recheck_market("0xabc", db=polily_db)
    assert result.new_status == "closed"
    state = get_market_state("0xabc", polily_db)
    assert state.status == "closed"


def test_recheck_unknown_market_raises(polily_db):
    with pytest.raises(ValueError, match="not found"):
        recheck_market("0xnonexistent", db=polily_db)


def test_recheck_not_expired_returns_current_status(polily_db):
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-04-01T10:00:00",
        title="Active Market",
        resolution_time="2099-12-31T00:00:00+00:00",
    ), polily_db)
    result = recheck_market("0xabc", db=polily_db)
    assert result.new_status == "watch"
    assert result.market_id == "0xabc"


def test_recheck_expired_sends_notification(polily_db):
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-03-30T10:00:00",
        title="Expired BTC Market",
        resolution_time="2026-03-31T00:00:00+00:00",
        price_at_watch=0.65,
    ), polily_db)
    recheck_market("0xabc", db=polily_db)
    from scanner.notifications import get_unread_notifications
    unread = get_unread_notifications(polily_db)
    assert len(unread) == 1
    assert "CLOSED" in unread[0]["title"]


def test_recheck_result_fields(polily_db):
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-03-30T10:00:00",
        title="Test",
        resolution_time="2026-03-31T00:00:00+00:00",
        price_at_watch=0.65,
        watch_sequence=2,
    ), polily_db)
    result = recheck_market("0xabc", db=polily_db)
    assert result.market_id == "0xabc"
    assert result.previous_price == 0.65
    assert result.watch_sequence == 2
