"""i18n smoke tests for PR-3 view migrations: monitor_list, score_result, archived_events."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import DataTable, Static

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.monitor_store import upsert_event_monitor
from polily.tui import i18n
from polily.tui.service import PolilyService


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.tui.heartbeat_seconds = 5.0
    cfg.tui.language = "zh"
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    s = PolilyService(config=cfg, db=db)
    yield s
    db.close()


def _all_static_text(view) -> str:
    parts = []
    for s in view.query(Static):
        val = getattr(s, "renderable", None) or getattr(s, "content", None)
        if val is not None:
            parts.append(str(val))
    return " ".join(parts)


@pytest.mark.asyncio
async def test_monitor_list_title_and_columns_flip(svc):
    # Seed at least one monitored event so the table is mounted.
    upsert_event(
        EventRow(event_id="ev1", title="Test Event", slug="test-slug", updated_at="now"),
        svc.db,
    )
    upsert_market(
        MarketRow(market_id="m1", event_id="ev1", question="Q", yes_price=0.42, updated_at="now"),
        svc.db,
    )
    upsert_event_monitor("ev1", auto_monitor=True, db=svc.db)

    from polily.tui.app import PolilyApp
    from polily.tui.views.monitor_list import MonitorListView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()

        table = view.query_one("#monitor-table", DataTable)
        zh_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "事件" in zh_labels
        assert "结构分" in zh_labels
        assert "监控列表" in _all_static_text(view)

        await app.action_toggle_language()
        await pilot.pause()

        en_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "Event" in en_labels
        assert "Score" in en_labels
        assert "事件" not in en_labels
        assert "Monitor List" in _all_static_text(view)


@pytest.mark.asyncio
async def test_score_result_titles_and_buttons_flip(svc):
    upsert_event(
        EventRow(event_id="ev2", title="Score Test", slug="score-test", updated_at="now"),
        svc.db,
    )
    upsert_market(
        MarketRow(market_id="m2", event_id="ev2", question="Q", yes_price=0.5, updated_at="now"),
        svc.db,
    )

    from polily.tui.app import PolilyApp
    from polily.tui.views.score_result import ScoreResultView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScoreResultView("ev2", svc)
        await app.mount(view)
        await pilot.pause()

        zh_text = _all_static_text(view)
        # Static labels
        assert "事件信息" in zh_text or "市场" in zh_text
        # Button labels
        from textual.widgets import Button
        buttons = [str(b.label) for b in view.query(Button)]
        joined_btns = " ".join(buttons)
        assert "重新评分" in joined_btns

        await app.action_toggle_language()
        await pilot.pause()

        en_text = _all_static_text(view)
        assert "Event Info" in en_text or "Market" in en_text
        buttons = [str(b.label) for b in view.query(Button)]
        joined_btns = " ".join(buttons)
        assert "Rescore" in joined_btns


@pytest.mark.asyncio
async def test_archived_events_title_and_columns_flip(svc):
    from polily.tui.app import PolilyApp
    from polily.tui.views.archived_events import ArchivedEventsView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ArchivedEventsView(svc)
        await app.mount(view)
        await pilot.pause()

        table = view.query_one("#archive-table", DataTable)
        zh_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "事件" in zh_labels
        assert "关闭于" in zh_labels
        assert "归档事件" in _all_static_text(view)

        await app.action_toggle_language()
        await pilot.pause()

        en_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "Event" in en_labels
        assert "Closed At" in en_labels
        assert "事件" not in en_labels
        assert "Archived Events" in _all_static_text(view)
