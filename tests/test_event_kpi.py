"""EventKpiRow — 子市场 card stays a bare count (no closed suffix)."""

from unittest.mock import MagicMock


def _mk_market(*, closed=0):
    m = MagicMock()
    m.closed = closed
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
