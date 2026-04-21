"""v0.8.0 Task 21: monitor_list view migrated to atoms + events + i18n."""
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import DataTable, Static

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.events import EventBus, TOPIC_MONITOR_UPDATED
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "m.db")
    upsert_event(EventRow(event_id="ev1", title="Test Event A", updated_at="now"), db)
    upsert_event(EventRow(event_id="ev2", title="Test Event B", updated_at="now"), db)
    # Seed auto_monitor flag to one event only.
    upsert_event_monitor(event_id="ev1", auto_monitor=True, db=db)
    s = ScanService(config=cfg, db=db, event_bus=EventBus())
    yield s
    db.close()


async def test_monitor_list_uses_polily_zones(svc):
    """Verify PolilyZone atoms are used in layout."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.monitor_list import MonitorListView
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 1, f"expected PolilyZone(s), found {len(zones)}"


async def test_monitor_list_chinese_labels(svc):
    """Core Chinese labels visible in rendered widgets."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.monitor_list import MonitorListView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()
        texts = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        joined = " ".join(texts)
        # At least one Chinese label from monitor_list should appear.
        found = False
        for lbl in ("监控", "开启", "关闭", "事件", "评分", "结构分"):
            if lbl in joined:
                found = True
                break
        assert found, f"no expected Chinese label found. Sample: {joined[:300]}"


async def test_monitor_list_subscribes_to_monitor_updated(svc):
    """Publish TOPIC_MONITOR_UPDATED; verify view calls call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.monitor_list import MonitorListView

    called = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()
        # v0.8.0 dispatch_to_ui picks call_later on UI thread or
        # call_from_thread on worker — patch both.
        def spy_ct(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))

        def spy_cl(*args, **kw):
            if len(args) >= 2:
                called.append(getattr(args[1], "__name__", str(args[1])))

        with patch.object(app, "call_from_thread", side_effect=spy_ct), \
             patch.object(app, "call_later", side_effect=spy_cl):
            svc.event_bus.publish(
                TOPIC_MONITOR_UPDATED,
                {"event_id": "ev1", "auto_monitor": False},
            )
            await pilot.pause()
        assert any(
            "render" in n.lower() or "refresh" in n.lower() or "update" in n.lower()
            for n in called
        ), f"monitor bus callback did not trigger re-render: {called}"


async def test_monitor_list_preserves_existing_fields(svc):
    """Q1 density: monitored events displayed with key fields intact."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.monitor_list import MonitorListView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MonitorListView(svc)
        await app.mount(view)
        await pilot.pause()

        texts = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        tables = list(view.query(DataTable))
        for t in tables:
            for row_key in t.rows:
                for col_key in t.columns:
                    try:
                        texts.append(str(t.get_cell(row_key, col_key)))
                    except Exception:
                        pass
        joined = " ".join(texts)
        # Only auto-monitored event is ev1 with title 'Test Event A'.
        assert "Test Event A" in joined, (
            f"monitored event title missing. Sample: {joined[:400]}"
        )
