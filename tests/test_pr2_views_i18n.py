"""i18n smoke tests for PR-2 view migrations: changelog, history, paper_status."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.widgets import Static

from polily.core.db import PolilyDB
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
async def test_changelog_view_title_flips_on_language_change(svc):
    """Only assert on the zone title — the markdown body contains historical
    references to "更新日志" / "Changelog" and would yield false positives if
    we matched against all rendered text."""
    from polily.tui.app import PolilyApp
    from polily.tui.views.changelog import ChangelogView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    async with app.run_test() as pilot:
        await pilot.pause()
        view = ChangelogView()
        await app.mount(view)
        await pilot.pause()
        zone_title = view.query_one("#changelog-zone .polily-zone-title", Static)
        zh_text = str(getattr(zone_title, "renderable", "") or getattr(zone_title, "content", ""))
        assert "更新日志" in zh_text

        await app.action_toggle_language()
        await pilot.pause()
        en_text = str(getattr(zone_title, "renderable", "") or getattr(zone_title, "content", ""))
        assert "Changelog" in en_text
        assert "更新日志" not in en_text


@pytest.mark.asyncio
async def test_history_view_title_and_columns_flip(svc):
    from polily.tui.app import PolilyApp
    from polily.tui.views.history import HistoryView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = HistoryView(svc)
        await app.mount(view)
        await pilot.pause()
        # Column headers — DataTable.columns is a dict[ColumnKey, Column];
        # iterate values and stringify .label which may be Text or str.
        from textual.widgets import DataTable
        table = view.query_one("#history-table", DataTable)
        zh_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "市场" in zh_labels
        assert "时间" in zh_labels
        assert "已实现交易历史" in _all_static_text(view)

        await app.action_toggle_language()
        await pilot.pause()

        en_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "Market" in en_labels
        assert "Time" in en_labels
        assert "市场" not in en_labels
        assert "Realized Trade History" in _all_static_text(view)


@pytest.mark.asyncio
async def test_paper_status_view_title_and_columns_flip(svc):
    from polily.tui.app import PolilyApp
    from polily.tui.views.paper_status import PaperStatusView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = PaperStatusView(svc)
        await app.mount(view)
        await pilot.pause()
        from textual.widgets import DataTable
        table = view.query_one("#portfolio-table", DataTable)
        zh_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "事件" in zh_labels
        assert "持仓" in _all_static_text(view)

        await app.action_toggle_language()
        await pilot.pause()
        en_labels = " ".join(str(c.label) for c in table.columns.values())
        assert "Event" in en_labels
        assert "事件" not in en_labels
        assert "Positions" in _all_static_text(view)
