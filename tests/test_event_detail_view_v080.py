"""v0.8.0 Task 19: event_detail view migrated to atoms + EventBus + r binding."""
from unittest.mock import MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.events import EventBus, TOPIC_PRICE_UPDATED
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "md.db")
    upsert_event(EventRow(event_id="ev1", title="Test Event", updated_at="now"), db)
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


async def test_event_detail_uses_multiple_polily_zones(svc):
    """event_detail is densest view — expects multiple PolilyZone sections."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 2, (
            f"event_detail should have 2+ PolilyZones (market info / score / etc.), "
            f"got {len(zones)}"
        )


async def test_event_detail_chinese_labels_in_rendered(svc):
    """Core Chinese labels visible."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView
    from textual.widgets import Static

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        texts = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        joined = " ".join(texts)
        # Core event-level labels that should appear (adjust if layout uses different wording)
        for lbl in ("事件",):
            assert lbl in joined, f"label {lbl} missing from rendered view"


async def test_event_detail_bus_callback_uses_call_from_thread(svc):
    """Publish TOPIC_PRICE_UPDATED; verify real handler uses call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView

    called = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = EventDetailView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        # v0.8.0 dispatch_to_ui picks `call_later` on UI thread,
        # `call_from_thread` on worker thread. Patch both so either path
        # is captured.
        def spy_ct(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))
        def spy_cl(*args, **kw):
            # call_later(delay, fn) — fn is args[1]
            if len(args) >= 2:
                called.append(getattr(args[1], "__name__", str(args[1])))
        with patch.object(app, "call_from_thread", side_effect=spy_ct), \
             patch.object(app, "call_later", side_effect=spy_cl):
            svc.event_bus.publish(
                TOPIC_PRICE_UPDATED,
                {"event_id": "ev1", "market_id": "m1", "mid": 0.5, "spread": 0.02},
            )
            await pilot.pause()
        assert any("render" in n.lower() or "refresh" in n.lower() or "update" in n.lower() for n in called), \
            f"price bus callback did not trigger re-render: {called}"


def test_event_detail_has_r_refresh_binding():
    """SF4: 'r' added to EventDetailView.BINDINGS with show=True."""
    from scanner.tui.views.event_detail import EventDetailView
    keys = {b.key: b.show for b in EventDetailView.BINDINGS}
    assert keys.get("r") is True, f"'r' refresh binding missing/hidden: {keys}"


def test_event_detail_preserves_existing_bindings():
    """Q1: a/t/m/v/o still present."""
    from scanner.tui.views.event_detail import EventDetailView
    keys = {b.key for b in EventDetailView.BINDINGS}
    for k in ("a", "t", "m", "v", "o", "escape"):
        assert k in keys, f"existing binding '{k}' missing"


async def test_event_detail_scroll_container_bounded(svc):
    """Regression for: AI 分析 zone covering other zones.

    When EventDetailView contains an analysis, the VerticalScroll must
    be height-bounded so all zones remain accessible without overflowing.
    """
    from scanner.analysis_store import AnalysisVersion, append_analysis
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.event_detail import EventDetailView
    from scanner.tui.widgets.polily_zone import PolilyZone
    from textual.containers import VerticalScroll

    # Seed a minimal analysis so the analysis zone is rendered
    av = AnalysisVersion(
        version=1,
        created_at="2026-01-01T00:00:00",
        narrative_output={"analysis": "test analysis text", "operations": []},
    )
    append_analysis("ev1", av, svc.db)

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = EventDetailView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()

        # VerticalScroll must exist inside EventDetailView
        scrolls = list(view.query(VerticalScroll))
        assert len(scrolls) >= 1, "EventDetailView must contain a VerticalScroll"

        # All expected zones must be in the DOM (not hidden/overflowed away)
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 3, (
            f"expected 3+ PolilyZones (事件信息 / 市场 / 持仓 + analysis), got {len(zones)}"
        )

        # The analysis zone specifically must be present when analysis exists
        analysis_zone = view.query_one("#analysis-zone")
        assert analysis_zone is not None, "analysis-zone must be in DOM when analyses exist"

        # The VerticalScroll must have explicit height (not auto) so it clips content
        scroll = scrolls[0]
        # Check that the CSS class chain includes our 1fr rule — verify via styles
        # Textual resolves '1fr' to a concrete height after layout; just confirm
        # the widget is not taller than the app screen (it used to overflow unbounded)
        scroll_height = scroll.size.height
        app_height = app.size.height
        assert scroll_height <= app_height, (
            f"VerticalScroll height ({scroll_height}) exceeds app height ({app_height}); "
            "analysis zone is overflowing the scroll container"
        )
