"""v0.8.0 Task 19: market_detail view migrated to atoms + EventBus + r binding."""
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


async def test_market_detail_uses_multiple_polily_zones(svc):
    """market_detail is densest view — expects multiple PolilyZone sections."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_detail import MarketDetailView
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketDetailView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 2, (
            f"market_detail should have 2+ PolilyZones (market info / score / etc.), "
            f"got {len(zones)}"
        )


async def test_market_detail_chinese_labels_in_rendered(svc):
    """Core Chinese labels visible."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_detail import MarketDetailView
    from textual.widgets import Static

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketDetailView(event_id="ev1", service=svc)
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


async def test_market_detail_bus_callback_uses_call_from_thread(svc):
    """Publish TOPIC_PRICE_UPDATED; verify real handler uses call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_detail import MarketDetailView

    called = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketDetailView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        original = app.call_from_thread
        def spy(fn, *a, **kw):
            called.append(getattr(fn, "__name__", str(fn)))
            return original(fn, *a, **kw)
        with patch.object(app, "call_from_thread", side_effect=spy):
            svc.event_bus.publish(
                TOPIC_PRICE_UPDATED,
                {"event_id": "ev1", "market_id": "m1", "mid": 0.5, "spread": 0.02},
            )
            await pilot.pause()
        assert any("render" in n.lower() or "refresh" in n.lower() or "update" in n.lower() for n in called), \
            f"price bus callback did not trigger re-render: {called}"


def test_market_detail_has_r_refresh_binding():
    """SF4: 'r' added to MarketDetailView.BINDINGS with show=True."""
    from scanner.tui.views.market_detail import MarketDetailView
    keys = {b.key: b.show for b in MarketDetailView.BINDINGS}
    assert keys.get("r") is True, f"'r' refresh binding missing/hidden: {keys}"


def test_market_detail_preserves_existing_bindings():
    """Q1: a/t/m/v/o still present."""
    from scanner.tui.views.market_detail import MarketDetailView
    keys = {b.key for b in MarketDetailView.BINDINGS}
    for k in ("a", "t", "m", "v", "o", "escape"):
        assert k in keys, f"existing binding '{k}' missing"
