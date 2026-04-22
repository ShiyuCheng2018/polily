"""EventKpiRow — 子市场 card stays a bare count (no closed suffix)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock


def _mk_market(*, closed=0, end_date=None, resolved_outcome=None):
    m = MagicMock()
    m.closed = closed
    m.end_date = end_date
    m.resolved_outcome = resolved_outcome
    m.yes_price = 0.5
    m.no_price = 0.5
    m.spread = 0.01
    m.structure_score = 70
    return m


def test_subcount_label_no_closed_suffix():
    from scanner.tui.components.event_kpi import _subcount_label
    markets = [_mk_market(closed=0), _mk_market(closed=1), _mk_market(closed=0)]
    assert _subcount_label(markets) == "3"


def test_subcount_label_all_open():
    from scanner.tui.components.event_kpi import _subcount_label
    markets = [_mk_market(closed=0) for _ in range(5)]
    assert _subcount_label(markets) == "5"


def test_subcount_label_all_closed_still_bare():
    from scanner.tui.components.event_kpi import _subcount_label
    markets = [_mk_market(closed=1) for _ in range(2)]
    assert _subcount_label(markets) == "2"


def test_kpi_end_label_active_uses_countdown_range():
    from scanner.tui.components.event_kpi import _kpi_end_label
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    near = (now + timedelta(days=3)).isoformat()
    far = (now + timedelta(days=40)).isoformat()
    event = MagicMock(); event.closed = 0; event.end_date = far
    markets = [_mk_market(end_date=near), _mk_market(end_date=far)]
    label = _kpi_end_label(event, markets, now=now)
    # Countdown range renders as e.g. '3天0小时 ~ 40天0小时'
    assert "天" in label
    assert "已结算" not in label
    assert "待全部结算" not in label


def test_kpi_end_label_awaiting_full_settlement():
    from scanner.tui.components.event_kpi import _kpi_end_label
    now = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)
    past = (now - timedelta(hours=1)).isoformat()
    event = MagicMock(); event.closed = 0; event.end_date = past
    markets = [_mk_market(closed=1, resolved_outcome=None)]  # SETTLING
    assert _kpi_end_label(event, markets, now=now) == "待全部结算"


def test_kpi_end_label_resolved():
    from scanner.tui.components.event_kpi import _kpi_end_label
    event = MagicMock(); event.closed = 1; event.end_date = None
    markets = [_mk_market(closed=1, resolved_outcome="no")]
    assert _kpi_end_label(event, markets) == "已结算"
