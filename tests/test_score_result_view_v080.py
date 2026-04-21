"""v0.8.0 Task 26: score_result view migrated to atoms + i18n."""
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.events import EventBus
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "s.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test Event", updated_at="now"),
        db,
    )
    yield ScanService(config=cfg, db=db, event_bus=EventBus())
    db.close()


async def test_score_result_uses_polily_zone(svc):
    from scanner.tui.app import PolilyApp
    from scanner.tui.views.score_result import ScoreResultView
    from scanner.tui.widgets.polily_zone import PolilyZone

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScoreResultView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        zones = list(view.query(PolilyZone))
        assert len(zones) >= 1, (
            f"expected at least 1 PolilyZone, found {len(zones)}"
        )


async def test_score_result_chinese_labels(svc):
    from textual.widgets import Static

    from scanner.tui.app import PolilyApp
    from scanner.tui.views.score_result import ScoreResultView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScoreResultView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        texts = []
        for s in view.query(Static):
            val = getattr(s, "renderable", None) or getattr(s, "content", None)
            if val:
                texts.append(str(val))
        joined = " ".join(texts)
        found = any(
            lbl in joined
            for lbl in ("评分", "结构", "市场", "事件", "流动性", "深度")
        )
        assert found, f"no expected Chinese label. Sample: {joined[:200]}"


async def test_score_result_preserves_existing_bindings(svc):
    """Q1 regression: escape/backspace must still work for go-back."""
    from scanner.tui.views.score_result import ScoreResultView

    keys = {b.key for b in ScoreResultView.BINDINGS}
    for k in ("escape", "backspace"):
        assert k in keys, f"binding '{k}' missing: {keys}"


async def test_score_result_vertical_scroll_bounded(svc):
    """Regression: scroll must be height-bounded so action bar stays visible."""
    from textual.containers import VerticalScroll

    from scanner.tui.app import PolilyApp
    from scanner.tui.views.score_result import ScoreResultView

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        view = ScoreResultView(event_id="ev1", service=svc)
        await app.mount(view)
        await pilot.pause()
        scrolls = list(view.query(VerticalScroll))
        assert len(scrolls) >= 1, "ScoreResultView must contain a VerticalScroll"
        scroll_height = scrolls[0].size.height
        app_height = app.size.height
        assert scroll_height <= app_height, (
            f"VerticalScroll height ({scroll_height}) exceeds app "
            f"height ({app_height}); zones are overflowing"
        )
