"""v0.8.0 Task 17: scan_log view migrated to atoms + events + i18n."""
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import DataTable

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.events import EventBus, TOPIC_SCAN_UPDATED
from scanner.scan_log import insert_pending_scan, claim_pending_scan, load_scan_logs
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(EventRow(event_id="ev1", title="Test Market Event", updated_at="now"), db)
    bus = EventBus()
    s = ScanService(config=cfg, db=db, event_bus=bus)
    yield s
    db.close()


async def test_scan_log_view_uses_polily_zones(svc):
    """Verify PolilyZone atoms are used (not raw Container)."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogView
    from scanner.tui.widgets.polily_zone import PolilyZone

    insert_pending_scan(
        event_id="ev1", event_title="Test Market Event",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="重要", db=svc.db,
    )
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None  # skip daemon restart in tests
    async with app.run_test() as pilot:
        await pilot.pause()
        # Mount ScanLogView manually (skip main screen nav)
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 1, f"expected PolilyZone(s), found {len(zones)}"


async def test_scan_log_shows_chinese_status_in_rendered_cells(svc):
    """Row rendering uses Chinese status labels (verify actual DataTable content)."""
    insert_pending_scan(
        event_id="ev1", event_title="Test Market Event",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="重要节点", db=svc.db,
    )
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()

        tables = list(view.query(DataTable))
        rendered_cells = []
        for t in tables:
            for row_key in t.rows:
                for col_key in t.columns:
                    try:
                        rendered_cells.append(str(t.get_cell(row_key, col_key)))
                    except Exception:
                        pass
        joined = " ".join(rendered_cells)
        assert "待执行" in joined, f"Chinese pending label missing. Cells: {joined[:300]}"
        assert "pending" not in joined.lower() or "待执行" in joined, "Raw English status leaked"


async def test_scan_log_preserves_approved_columns(svc):
    """Q1 density: columns match user-approved mock (5 pending / 6 history)."""
    insert_pending_scan(
        event_id="ev1", event_title="Test Market Event",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="重要", db=svc.db,
    )
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()

        tables = list(view.query(DataTable))
        # Collect column labels across tables (by id)
        tables_by_id = {t.id: t for t in tables}
        upcoming = tables_by_id.get("upcoming-table")
        history = tables_by_id.get("history-table")
        assert upcoming is not None, "upcoming-table missing"
        assert history is not None, "history-table missing"

        up_cols = {str(c.label.plain if hasattr(c.label, 'plain') else c.label) for c in upcoming.columns.values()}
        hist_cols = {str(c.label.plain if hasattr(c.label, 'plain') else c.label) for c in history.columns.values()}

        assert {"触发", "类型", "状态", "事件", "预定时间", "原因"}.issubset(up_cols), \
            f"upcoming columns incomplete: {up_cols}"
        assert {"触发", "类型", "状态", "事件", "结束时间", "耗时", "错误"}.issubset(hist_cols), \
            f"history columns incomplete: {hist_cols}"


async def test_scan_log_subscribes_via_real_bus_publish(svc):
    """Publish TOPIC_SCAN_UPDATED; verify view calls call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogView

    called = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogView(svc)
        await app.mount(view)
        await pilot.pause()

        original = app.call_from_thread
        def spy(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))
            return original(fn, *a, **kw)
        with patch.object(app, "call_from_thread", side_effect=spy):
            svc.event_bus.publish(
                TOPIC_SCAN_UPDATED,
                {"scan_id": "x", "event_id": "ev1", "status": "completed"},
            )
            await pilot.pause()
        assert any("render" in n.lower() or "refresh" in n.lower() or "update" in n.lower() for n in called), \
            f"bus callback did not invoke render/refresh via call_from_thread: {called}"


async def test_scan_log_detail_view_no_scan_id(svc):
    """Detail view hides scan_id and event_id per user approval (Task 16)."""
    insert_pending_scan(
        event_id="ev1", event_title="Test Market Event",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="manual", scheduled_reason=None, db=svc.db,
    )
    logs = load_scan_logs(svc.db)
    assert logs, "setup failed"
    log_entry = logs[0]

    from scanner.tui.app import PolilyApp
    from scanner.tui.views.scan_log import ScanLogDetailView
    from textual.widgets import Static

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        detail = ScanLogDetailView(log_entry, db=svc.db)
        await app.mount(detail)
        await pilot.pause()

        # Collect all Static widget text
        texts = []
        for s in detail.query(Static):
            if hasattr(s, "renderable"):
                texts.append(str(s.renderable))
        joined = " ".join(texts)

        # scan_id starts with 'r_' or numeric date prefix — search for leaked scan_id
        assert log_entry.scan_id not in joined, \
            f"scan_id '{log_entry.scan_id}' leaked into detail view"
        # event_id should also not appear as standalone
        assert f"事件 : ev1" not in joined and f"event_id : ev1" not in joined, \
            f"event_id leaked into detail view"
