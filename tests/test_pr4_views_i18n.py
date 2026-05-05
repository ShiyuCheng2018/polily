"""i18n smoke tests for PR-4 view migrations: scan_log + event_detail."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import DataTable, Static

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
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
async def test_scan_log_titles_and_columns_flip(svc):
    from polily.tui.app import PolilyApp
    from polily.tui.views.scan_log import ScanLogView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()

        # Static title + zone titles
        zh_text = _all_static_text(view)
        assert "任务记录" in zh_text
        assert "任务队列" in zh_text
        assert "历史" in zh_text

        # Pending and history table column headers
        up = view.query_one("#upcoming-table", DataTable)
        hist = view.query_one("#history-table", DataTable)
        zh_up = " ".join(str(c.label) for c in up.columns.values())
        zh_hist = " ".join(str(c.label) for c in hist.columns.values())
        assert "触发" in zh_up
        assert "原因" in zh_up
        assert "耗时" in zh_hist

        await app.action_toggle_language()
        await pilot.pause()

        en_text = _all_static_text(view)
        assert "Task Log" in en_text
        assert "Queue" in en_text
        assert "History" in en_text
        en_up = " ".join(str(c.label) for c in up.columns.values())
        en_hist = " ".join(str(c.label) for c in hist.columns.values())
        assert "Trigger" in en_up
        assert "Reason" in en_up
        assert "Elapsed" in en_hist
        # zh strings should be gone from the column labels
        assert "触发" not in en_up
        assert "耗时" not in en_hist


@pytest.mark.asyncio
async def test_event_detail_zone_titles_and_state_breakdown_flip(svc):
    upsert_event(
        EventRow(event_id="ev1", title="Detail Test", slug="detail-test", updated_at="now"),
        svc.db,
    )
    upsert_market(
        MarketRow(
            market_id="m1", event_id="ev1", question="Q",
            yes_price=0.42, updated_at="now",
        ),
        svc.db,
    )

    from polily.tui.app import PolilyApp
    from polily.tui.views.event_detail import EventDetailView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView("ev1", svc)
        await app.mount(view)
        await pilot.pause()

        zh_text = _all_static_text(view)
        # Zone titles
        assert "事件信息" in zh_text
        assert "市场" in zh_text
        assert "持仓" in zh_text
        # Single-market state breakdown
        assert "(交易中)" in zh_text

        await app.action_toggle_language()
        await pilot.pause()

        en_text = _all_static_text(view)
        assert "Event Info" in en_text
        # Zone title for "市场" → "Market"; "(Trading)" comes from state breakdown.
        assert "(Trading)" in en_text
        assert "Position" in en_text
        # zh label gone
        assert "事件信息" not in en_text
        assert "(交易中)" not in en_text
