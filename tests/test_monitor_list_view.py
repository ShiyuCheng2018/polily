"""MonitorListView rendering contract."""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable

from scanner.core.db import PolilyDB
from scanner.monitor.store import append_movement
from scanner.tui.service import ScanService
from tests.conftest import make_event, setup_event_and_market


def _service() -> ScanService:
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(tmp.name) / "polily.db")
    svc = ScanService(config=cfg, db=db)
    svc._tmp = tmp
    return svc


def _seed_monitored_event(service, event_id: str, title: str, score: float):
    from scanner.core.event_store import upsert_event
    from scanner.core.monitor_store import upsert_event_monitor

    setup_event_and_market(
        service.db, event_id=event_id, market_id=f"m-{event_id}",
    )
    upsert_event(make_event(event_id=event_id, title=title), service.db)
    # structure_score is excluded from upsert_event — set it directly.
    service.db.conn.execute(
        "UPDATE events SET structure_score = ? WHERE event_id = ?", (score, event_id),
    )
    upsert_event_monitor(event_id=event_id, auto_monitor=True, db=service.db)
    service.db.conn.execute(
        "UPDATE event_monitors SET next_check_at = ? WHERE event_id = ?",
        ("2027-01-01T09:00:00+00:00", event_id),
    )
    service.db.conn.commit()


class _Host(App):
    def __init__(self, widget):
        super().__init__()
        self._widget = widget

    def compose(self) -> ComposeResult:
        yield self._widget


@pytest.mark.asyncio
async def test_columns_match_new_spec():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        labels = [str(c.label) for c in table.columns.values()]

    assert "事件" in labels
    assert any("结构分" in lab or "分数" in lab for lab in labels)
    assert "子市场" in labels
    assert any("AI" in lab for lab in labels)
    assert "异动" in labels
    assert "结算" in labels
    assert any("下次检查" in lab for lab in labels)
    # Removed 状态 column
    assert "状态" not in labels


@pytest.mark.asyncio
async def test_renders_settlement_window_range_for_multi_market_event():
    from scanner.core.event_store import MarketRow, upsert_market
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    # Add a second market with a later end_date → settlement column should
    # show a range ('… ~ …').
    svc.db.conn.execute(
        "UPDATE markets SET end_date = ? WHERE market_id = 'm-evA'",
        ("2027-05-01T00:00:00+00:00",),
    )
    upsert_market(
        MarketRow(
            market_id="m-evA-2", event_id="evA", question="second market",
            end_date="2027-11-01T00:00:00+00:00", closed=0,
            updated_at="2026-04-19T00:00:00",
        ),
        svc.db,
    )
    svc.db.conn.commit()

    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    assert " ~ " in flat  # range separator with spaces


@pytest.mark.asyncio
async def test_renders_settlement_single_value_for_binary_event():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    svc.db.conn.execute(
        "UPDATE markets SET end_date = ? WHERE market_id = 'm-evA'",
        ("2027-05-01T00:00:00+00:00",),
    )
    svc.db.conn.commit()

    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        # 结算 cell specifically — find its column index
        labels = [str(c.label) for c in table.columns.values()]
        idx = labels.index("结算")
        settlement_cell = str(table.get_row(row_key)[idx])

    assert "~" not in settlement_cell  # single value only


@pytest.mark.asyncio
async def test_renders_score_and_subcount_and_next_check():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "US × Iran peace deal", score=82.0)
    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        # First (and only) row
        row_key = next(iter(table.rows.keys()))
        cells = [str(c) for c in table.get_row(row_key)]
        flat = " ".join(cells)

    assert "82" in flat  # structure score
    assert "2027-01-01" in flat  # full date with year
    assert "(" in flat and ")" in flat  # relative time in parens


@pytest.mark.asyncio
async def test_renders_ai_version_dash_when_no_analyses():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    assert "—" in flat  # AI 版 dash


@pytest.mark.asyncio
async def test_renders_ai_version_with_count():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    for v in (1, 2, 3):
        svc.db.conn.execute(
            "INSERT INTO analyses (event_id, version, created_at, narrative_output) "
            "VALUES (?, ?, ?, '{}')", ("evA", v, f"2026-04-19T00:0{v}:00"),
        )
    svc.db.conn.commit()

    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    assert "v3" in flat


@pytest.mark.asyncio
async def test_renders_movement_label():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    append_movement(
        event_id="evA", market_id="m-evA",
        yes_price=0.6, magnitude=72.0, quality=85.0, label="consensus",
        db=svc.db,
    )
    svc.db.conn.commit()

    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    assert "共识异动" in flat
    assert "M:72" in flat
    assert "Q:85" in flat


@pytest.mark.asyncio
async def test_toggle_monitor_blocked_by_positions():
    """Watchlist `m` must obey the same guard as MarketDetail: a monitored
    event with open positions cannot be unmonitored."""
    from scanner.core.monitor_store import get_event_monitor
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    svc.db.conn.execute(
        "INSERT INTO positions (event_id, market_id, side, shares, avg_cost, "
        "cost_basis, title, opened_at, updated_at) "
        "VALUES ('evA', 'm-evA', 'yes', 10.0, 0.5, 5.0, 'Q', 'now', 'now')",
    )
    svc.db.conn.commit()

    view = MonitorListView(svc)

    class _Capture(App):
        def __init__(self, w):
            super().__init__()
            self._w = w
            self.pushed_modals: list = []

        def compose(self) -> ComposeResult:
            yield self._w

        def push_screen(self, screen, callback=None):
            self.pushed_modals.append((screen, callback))

    host = _Capture(view)
    notify_calls: list = []
    async with host.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        view.notify = lambda msg, **kw: notify_calls.append((msg, kw))  # type: ignore[assignment]
        view.focus()
        await pilot.press("m")
        await pilot.pause()
        pushed = list(host.pushed_modals)

    assert get_event_monitor("evA", svc.db)["auto_monitor"] == 1  # still monitored
    assert not pushed  # no modal — blocked inline
    assert notify_calls
    assert "无法" in notify_calls[0][0]


@pytest.mark.asyncio
async def test_toggle_monitor_pushes_modal_when_no_positions():
    """No positions → modal appears, toggle only fires on confirm-dismiss."""
    from scanner.core.monitor_store import get_event_monitor
    from scanner.tui.views.monitor_list import MonitorListView
    from scanner.tui.views.monitor_modals import ConfirmUnmonitorModal

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)

    view = MonitorListView(svc)

    class _Capture(App):
        def __init__(self, w):
            super().__init__()
            self._w = w
            self.pushed_modals: list = []

        def compose(self) -> ComposeResult:
            yield self._w

        def push_screen(self, screen, callback=None):
            self.pushed_modals.append((screen, callback))

    host = _Capture(view)
    async with host.run_test(size=(180, 40)) as pilot:
        await pilot.pause()
        view.focus()
        await pilot.press("m")
        await pilot.pause()
        pushed = list(host.pushed_modals)
        assert len(pushed) == 1
        modal, cb = pushed[0]
        assert isinstance(modal, ConfirmUnmonitorModal)
        # Not yet toggled
        assert get_event_monitor("evA", svc.db)["auto_monitor"] == 1
        # Confirm → toggles off
        cb(True)
        await pilot.pause()

    assert get_event_monitor("evA", svc.db)["auto_monitor"] == 0


@pytest.mark.asyncio
async def test_movement_dash_when_no_movement():
    from scanner.tui.views.monitor_list import MonitorListView

    svc = _service()
    _seed_monitored_event(svc, "evA", "Event A", score=82.0)
    view = MonitorListView(svc)
    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    # AI 版 dash + movement dash — both "—" present somewhere
    assert flat.count("—") >= 2
