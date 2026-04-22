"""Tests for EventHeader — binary breadcrumb (Rich markup) +
multi-market settlement label."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock


def _mk_market(*, closed=0, end_date=None, resolved_outcome=None):
    m = MagicMock()
    m.closed = closed
    m.end_date = end_date
    m.resolved_outcome = resolved_outcome
    return m


def test_binary_breadcrumb_trading_rich_markup():
    """TRADING: countdown shown normally, future states tagged [dim]."""
    from scanner.tui.components.event_header import _binary_breadcrumb
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=7)).isoformat()
    m = _mk_market(end_date=future)
    text = _binary_breadcrumb(m, now=now)
    # All 3 future states are dim-tagged (Rich markup, not literal brackets)
    assert "[dim]即将结算[/]" in text
    assert "[dim]结算中[/]" in text
    assert "[dim]已结算[/]" in text
    # No checkmarks yet
    assert "✓" not in text


def test_binary_breadcrumb_pending_settlement_highlights_current():
    from scanner.tui.components.event_header import _binary_breadcrumb
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    past = (now - timedelta(hours=1)).isoformat()
    m = _mk_market(end_date=past)
    text = _binary_breadcrumb(m, now=now)
    # Leading phrase
    assert "名义已过期" in text
    # Current state highlighted via Rich $primary color bold
    assert "[b $primary]即将结算[/]" in text
    # Future states still dim
    assert "[dim]结算中[/]" in text
    assert "[dim]已结算[/]" in text
    # No checkmarks yet
    assert "✓" not in text


def test_binary_breadcrumb_settling_marks_prior_done():
    from scanner.tui.components.event_header import _binary_breadcrumb
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome=None)
    text = _binary_breadcrumb(m, now=now)
    assert "已锁盘" in text
    assert "[dim]即将结算 ✓[/]" in text
    assert "[b $primary]结算中[/]" in text
    assert "[dim]已结算[/]" in text


def test_binary_breadcrumb_settled_with_winner_suffix():
    from scanner.tui.components.event_header import _binary_breadcrumb
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome="no")
    text = _binary_breadcrumb(m, now=now)
    assert "[dim]即将结算 ✓[/]" in text
    assert "[dim]结算中 ✓[/]" in text
    assert "[b $primary]已结算 NO 获胜[/]" in text


def test_multi_event_settlement_label_active():
    from scanner.tui.components.event_header import _multi_event_settlement_label
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=7)).isoformat()
    past = (now - timedelta(hours=1)).isoformat()
    event = MagicMock()
    event.closed = 0
    event.end_date = future
    markets = [_mk_market(end_date=future), _mk_market(end_date=past)]
    label = _multi_event_settlement_label(event, markets, now=now)
    # Event countdown renders via format_countdown
    assert "待全部结算" not in label


def test_multi_event_settlement_label_awaiting_full():
    from scanner.tui.components.event_header import _multi_event_settlement_label
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    past = (now - timedelta(hours=1)).isoformat()
    event = MagicMock()
    event.closed = 0
    event.end_date = past
    markets = [_mk_market(closed=1, resolved_outcome=None)]  # SETTLING
    assert _multi_event_settlement_label(event, markets, now=now) == "待全部结算"


def test_multi_event_settlement_label_resolved():
    from scanner.tui.components.event_header import _multi_event_settlement_label
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    event = MagicMock()
    event.closed = 1
    event.end_date = None
    markets = [_mk_market(closed=1, resolved_outcome="no")]
    assert _multi_event_settlement_label(event, markets, now=now) == "已结算"
