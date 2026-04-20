"""v0.8.0 Task 22: market_list view migrated to atoms + events + i18n."""
from unittest.mock import MagicMock, patch

import pytest
from textual.widgets import DataTable, Static

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.events import EventBus, TOPIC_PRICE_UPDATED
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "m.db")
    upsert_event(
        EventRow(
            event_id="ev1",
            title="Test Event Alpha",
            structure_score=78.0,
            volume=123456.0,
            market_count=1,
            updated_at="now",
        ),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1",
            event_id="ev1",
            question="Will X happen?",
            yes_price=0.42,
            updated_at="now",
        ),
        db,
    )
    s = ScanService(config=cfg, db=db, event_bus=EventBus())
    yield s
    db.close()


def _events_for_view(svc):
    """Shape ScanService.get_all_events() output for MarketListView ctor."""
    return svc.get_all_events()


async def test_market_list_uses_polily_zone(svc):
    """Verify PolilyZone atom wraps the list."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_list import MarketListView
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketListView(_events_for_view(svc), svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 1, f"expected PolilyZone(s), found {len(zones)}"


async def test_market_list_chinese_labels(svc):
    """Core Chinese labels appear somewhere in rendered view."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_list import MarketListView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketListView(_events_for_view(svc), svc)
        await app.mount(view)
        await pilot.pause()

        texts: list[str] = []
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
            # Column header labels also count.
            for col in t.columns.values():
                texts.append(str(getattr(col, "label", "")))

        joined = " ".join(texts)
        found = any(lbl in joined for lbl in ("事件", "市场", "研究", "评分"))
        assert found, f"no expected Chinese label found. Sample: {joined[:300]}"


async def test_market_list_bus_callback_uses_call_from_thread(svc):
    """Publish TOPIC_PRICE_UPDATED; verify view re-renders via call_from_thread."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_list import MarketListView

    called: list[str] = []
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketListView(_events_for_view(svc), svc)
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
        assert any(
            "render" in n.lower() or "refresh" in n.lower() or "update" in n.lower()
            for n in called
        ), f"price bus callback did not trigger re-render: {called}"


async def test_market_list_preserves_event_title(svc):
    """Q1 density: event title present, internal IDs hidden."""
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.market_list import MarketListView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = MarketListView(_events_for_view(svc), svc)
        await app.mount(view)
        await pilot.pause()

        texts: list[str] = []
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
        assert "Test Event Alpha" in joined, (
            f"event title missing from view. Sample: {joined[:400]}"
        )
        # Internal IDs must not be surfaced as standalone text.
        assert "ev1" not in joined, (
            f"internal event_id leaked to UI. Sample: {joined[:400]}"
        )
