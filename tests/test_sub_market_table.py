"""Tests for SubMarketTable — settlement column state labels."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock


def _mk_market(
    *, market_id="m1", closed=0, end_date=None, resolved_outcome=None,
    yes_price=0.5, no_price=0.5, spread=0.01, volume=1000,
    structure_score=70, score_breakdown=None,
):
    m = MagicMock()
    m.market_id = market_id
    m.closed = closed
    m.end_date = end_date
    m.resolved_outcome = resolved_outcome
    m.yes_price = yes_price
    m.no_price = no_price
    m.spread = spread
    m.volume = volume
    m.structure_score = structure_score
    m.score_breakdown = score_breakdown
    m.group_item_title = None
    m.question = "Q"
    m.market_type = "other"
    return m


def test_settlement_cell_trading_exact_countdown():
    """TRADING: countdown string includes the date portion.

    NOTE: `format_countdown` uses `datetime.now(UTC)` internally, ignoring
    the `now=now` kwarg of `_settlement_cell_text`. Asserting relative phrasing
    like "3天" would break after wall-clock drift. Keep the date portion
    (wall-clock independent) as the only brittle-free assertion.
    """
    from scanner.tui.components.sub_market_table import _settlement_cell_text
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    future = (now + timedelta(days=3)).isoformat()
    m = _mk_market(closed=0, end_date=future)
    text = _settlement_cell_text(m, now=now)
    assert "04-25" in text
    # State label should NOT appear for TRADING
    assert "即将结算" not in text
    assert "结算中" not in text
    assert "已结算" not in text


def test_settlement_cell_pending_settlement_exact_label():
    from scanner.tui.components.sub_market_table import _settlement_cell_text
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    past = (now - timedelta(hours=1)).isoformat()
    m = _mk_market(closed=0, end_date=past)
    assert _settlement_cell_text(m, now=now) == "[即将结算]"


def test_settlement_cell_settling_exact_label():
    """closed=1, resolved_outcome=None → SETTLING."""
    from scanner.tui.components.sub_market_table import _settlement_cell_text
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome=None)
    assert _settlement_cell_text(m, now=now) == "[结算中]"


def test_settlement_cell_settled_exact_label():
    """closed=1, resolved_outcome='no' → SETTLED (no winner suffix in cell — column is narrow)."""
    from scanner.tui.components.sub_market_table import _settlement_cell_text
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    m = _mk_market(closed=1, resolved_outcome="no")
    assert _settlement_cell_text(m, now=now) == "[已结算]"
