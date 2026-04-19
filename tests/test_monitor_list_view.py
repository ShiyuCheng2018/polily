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
    async with _Host(view).run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#monitor-table", DataTable)
        labels = [str(c.label) for c in table.columns.values()]

    assert "事件" in labels
    assert any("结构分" in lab or "分数" in lab for lab in labels)
    assert "子市场" in labels
    assert any("AI" in lab for lab in labels)
    assert "异动" in labels
    assert any("下次检查" in lab for lab in labels)
    # Removed 状态 column
    assert "状态" not in labels


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
