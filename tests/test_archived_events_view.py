"""ArchivedEventsView rendering + navigation contract."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import ScanService


def _service():
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    cfg.wallet.starting_balance = 100.0
    tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(tmp.name) / "t.db")
    svc = ScanService(config=cfg, db=db)
    svc._tmp = tmp
    return svc


def _seed_archived(svc, event_id: str, title: str, score: float = 82.0):
    upsert_event(
        EventRow(event_id=event_id, title=title, closed=1,
                 updated_at="2026-04-19T00:00:00"),
        svc.db,
    )
    svc.db.conn.execute(
        "UPDATE events SET structure_score=? WHERE event_id=?", (score, event_id),
    )
    upsert_market(
        MarketRow(market_id=f"m-{event_id}", event_id=event_id, question="Q",
                  updated_at="2026-04-19T00:00:00"),
        svc.db,
    )
    upsert_event_monitor(event_id, auto_monitor=True, db=svc.db)
    svc.db.conn.commit()


class _Host(App):
    def __init__(self, view):
        super().__init__()
        self._view = view
        self.pushed: list = []

    def compose(self) -> ComposeResult:
        yield self._view

    def push_screen(self, screen, callback=None):
        self.pushed.append((screen, callback))


@pytest.mark.asyncio
async def test_column_spec():
    from scanner.tui.views.archived_events import ArchivedEventsView

    svc = _service()
    _seed_archived(svc, "evA", "Sample event")
    view = ArchivedEventsView(svc)
    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#archive-table", DataTable)
        labels = [str(c.label) for c in table.columns.values()]

    assert "事件" in labels
    assert "结构分" in labels
    assert "子市场" in labels
    assert "关闭于" in labels


@pytest.mark.asyncio
async def test_empty_state_shows_placeholder():
    from scanner.tui.views.archived_events import ArchivedEventsView

    svc = _service()  # no archived events
    view = ArchivedEventsView(svc)
    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        flat = " ".join(str(s.render()) for s in view.query(Static))

    assert "暂无归档" in flat


@pytest.mark.asyncio
async def test_renders_archived_row_content():
    from scanner.tui.views.archived_events import ArchivedEventsView

    svc = _service()
    _seed_archived(svc, "evA", "US-Iran nuclear deal", score=73.0)
    view = ArchivedEventsView(svc)
    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#archive-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    assert "US-Iran nuclear deal" in flat
    assert "73" in flat  # structure score
    assert "二元" in flat  # market count formatter (1 market)
    assert "2026-04-19" in flat  # closed at


@pytest.mark.asyncio
async def test_enter_posts_view_archived_detail():
    from scanner.tui.views.archived_events import ArchivedEventsView, ViewArchivedDetail

    svc = _service()
    _seed_archived(svc, "evA", "Sample event")
    view = ArchivedEventsView(svc)
    captured: list[ViewArchivedDetail] = []

    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        original_post = view.post_message

        def _intercept(msg):
            if isinstance(msg, ViewArchivedDetail):
                captured.append(msg)
            return original_post(msg)

        view.post_message = _intercept  # type: ignore[assignment]
        view.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert len(captured) == 1
    assert captured[0].event_id == "evA"


@pytest.mark.asyncio
async def test_score_none_renders_dash():
    """NULL structure_score renders '—' in the score cell, not 'None' or garbage."""
    from scanner.tui.views.archived_events import ArchivedEventsView

    svc = _service()
    # Seed with score=None (structure_score column left NULL).
    upsert_event(
        EventRow(event_id="evNoScore", title="Unscored event", closed=1,
                 updated_at="2026-04-19T00:00:00"),
        svc.db,
    )
    upsert_market(
        MarketRow(market_id="m-evNoScore", event_id="evNoScore", question="Q",
                  updated_at="2026-04-19T00:00:00"),
        svc.db,
    )
    upsert_event_monitor("evNoScore", auto_monitor=True, db=svc.db)
    svc.db.conn.commit()

    view = ArchivedEventsView(svc)
    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#archive-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        cells = [str(c) for c in table.get_row(row_key)]

    # The em-dash renders in the score cell specifically; assert it's present
    # in the row (and that no trace of 'None' appears).
    flat = " ".join(cells)
    assert "—" in flat
    assert "None" not in flat


@pytest.mark.asyncio
async def test_multi_market_count_rendered():
    """Multi-market events render as 'N 个', not '二元'."""
    from scanner.tui.views.archived_events import ArchivedEventsView

    svc = _service()
    upsert_event(
        EventRow(event_id="evMulti", title="Multi-outcome event", closed=1,
                 updated_at="2026-04-19T00:00:00"),
        svc.db,
    )
    svc.db.conn.execute(
        "UPDATE events SET structure_score=? WHERE event_id=?", (70.0, "evMulti"),
    )
    # Two sub-markets under the same event.
    for i in range(2):
        upsert_market(
            MarketRow(market_id=f"m-evMulti-{i}", event_id="evMulti",
                      question=f"Q{i}", updated_at="2026-04-19T00:00:00"),
            svc.db,
        )
    upsert_event_monitor("evMulti", auto_monitor=True, db=svc.db)
    svc.db.conn.commit()

    view = ArchivedEventsView(svc)
    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        table = view.query_one("#archive-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        flat = " ".join(str(c) for c in table.get_row(row_key))

    assert "2 个" in flat
    assert "二元" not in flat


@pytest.mark.asyncio
async def test_row_click_posts_view_archived_detail():
    """DataTable.RowSelected handler is wired to post ViewArchivedDetail.

    Row-click in a Textual DataTable with `cursor_type='row'` ultimately
    surfaces as a RowSelected message. This test exercises the handler path
    (`on_data_table_row_selected`) separately from the keyboard path
    (`action_view_detail`) so a regression in either won't hide behind the
    other.
    """
    from scanner.tui.views.archived_events import ArchivedEventsView, ViewArchivedDetail

    svc = _service()
    _seed_archived(svc, "evClick", "Clickable event")
    view = ArchivedEventsView(svc)
    captured: list[ViewArchivedDetail] = []

    async with _Host(view).run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        original_post = view.post_message

        def _intercept(msg):
            if isinstance(msg, ViewArchivedDetail):
                captured.append(msg)
            return original_post(msg)

        view.post_message = _intercept  # type: ignore[assignment]
        # Directly invoke the handler Textual wires up for row-clicks /
        # row-Enter. We pass a minimal message — the handler only reads
        # the view's own cursor state via `_selected_event_id()`.
        table = view.query_one("#archive-table", DataTable)
        row_key = next(iter(table.rows.keys()))
        view.on_data_table_row_selected(
            DataTable.RowSelected(data_table=table, cursor_row=0, row_key=row_key),
        )
        await pilot.pause()

    assert len(captured) == 1
    assert captured[0].event_id == "evClick"
