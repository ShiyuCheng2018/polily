"""Tests for event_detail 市场 PolilyZone title — state breakdown string."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock


def _mk_market(*, closed=0, end_date=None, resolved_outcome=None):
    m = MagicMock()
    m.closed = closed
    m.end_date = end_date
    m.resolved_outcome = resolved_outcome
    return m


def test_market_zone_title_multi_all_trading():
    from polily.tui.views.event_detail import _market_zone_title_suffix
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=5)).isoformat()
    markets = [_mk_market(end_date=future) for _ in range(3)]
    assert _market_zone_title_suffix(markets, now=now) == (
        "(活跃 3, 即将结算 0, 结算中 0, 已结算 0)"
    )


def test_market_zone_title_multi_mixed():
    from polily.tui.views.event_detail import _market_zone_title_suffix
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=5)).isoformat()
    past = (now - timedelta(hours=1)).isoformat()
    markets = [
        _mk_market(end_date=future),                          # TRADING
        _mk_market(end_date=future),                          # TRADING
        _mk_market(end_date=future),                          # TRADING
        _mk_market(end_date=past),                            # PENDING_SETTLEMENT
        _mk_market(closed=1, resolved_outcome="no"),          # SETTLED
    ]
    assert _market_zone_title_suffix(markets, now=now) == (
        "(活跃 3, 即将结算 1, 结算中 0, 已结算 1)"
    )


def test_market_zone_title_multi_with_settling():
    from polily.tui.views.event_detail import _market_zone_title_suffix
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    markets = [
        _mk_market(closed=1, resolved_outcome=None),          # SETTLING
        _mk_market(closed=1, resolved_outcome="yes"),         # SETTLED
    ]
    assert _market_zone_title_suffix(markets, now=now) == (
        "(活跃 0, 即将结算 0, 结算中 1, 已结算 1)"
    )


def test_market_zone_title_binary_trading():
    from polily.tui.views.event_detail import _market_zone_title_suffix
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=5)).isoformat()
    assert _market_zone_title_suffix([_mk_market(end_date=future)], now=now) == "(交易中)"


def test_market_zone_title_binary_settled_with_winner():
    from polily.tui.views.event_detail import _market_zone_title_suffix
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome="no")
    assert _market_zone_title_suffix([m], now=now) == "(已结算 NO 获胜)"


def test_market_zone_title_binary_settling():
    """Binary SETTLING (closed=1, outcome=None) renders without winner suffix."""
    from polily.tui.views.event_detail import _market_zone_title_suffix
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome=None)
    assert _market_zone_title_suffix([m], now=now) == "(结算中)"


def test_market_zone_title_empty_markets():
    from polily.tui.views.event_detail import _market_zone_title_suffix
    assert _market_zone_title_suffix([]) == ""
