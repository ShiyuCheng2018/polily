"""Tests for watch recheck orchestration."""

import tempfile
from pathlib import Path

import pytest

from scanner.db import PolilyDB
from scanner.market_state import MarketState, get_market_state, set_market_state
from scanner.watch_recheck import RecheckResult, recheck_market


def _make_db():
    tmp = tempfile.mkdtemp()
    return PolilyDB(Path(tmp) / "polily.db")


def test_recheck_expired_market_closes():
    db = _make_db()
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-03-30T10:00:00",
        title="Expired Market",
        resolution_time="2026-03-31T00:00:00+00:00",
        price_at_watch=0.65,
    ), db)
    result = recheck_market("0xabc", db=db)
    assert result.new_status == "closed"
    state = get_market_state("0xabc", db)
    assert state.status == "closed"
    db.close()


def test_recheck_unknown_market_raises():
    db = _make_db()
    with pytest.raises(ValueError, match="not found"):
        recheck_market("0xnonexistent", db=db)
    db.close()


def test_recheck_not_expired_returns_current_status():
    """Without service, recheck just validates expiry and returns current status."""
    db = _make_db()
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-04-01T10:00:00",
        title="Active Market",
        resolution_time="2099-12-31T00:00:00+00:00",
    ), db)
    result = recheck_market("0xabc", db=db)
    assert result.new_status == "watch"
    assert result.market_id == "0xabc"
    db.close()


def test_recheck_expired_sends_notification():
    db = _make_db()
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-03-30T10:00:00",
        title="Expired BTC Market",
        resolution_time="2026-03-31T00:00:00+00:00",
        price_at_watch=0.65,
    ), db)
    recheck_market("0xabc", db=db)
    # Check notification was created
    from scanner.notifications import get_unread_notifications
    unread = get_unread_notifications(db)
    assert len(unread) == 1
    assert "CLOSED" in unread[0]["title"]
    db.close()


def test_recheck_result_fields():
    db = _make_db()
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-03-30T10:00:00",
        title="Test",
        resolution_time="2026-03-31T00:00:00+00:00",
        price_at_watch=0.65,
        watch_sequence=2,
    ), db)
    result = recheck_market("0xabc", db=db)
    assert result.market_id == "0xabc"
    assert result.previous_price == 0.65
    assert result.watch_sequence == 2
    db.close()
