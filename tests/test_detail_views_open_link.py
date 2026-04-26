"""`o` binding opens the Polymarket event link from ScoreResultView and
ScanLogDetailView (parity with EventDetailView).

Contract:
- Both views declare `Binding("o", "open_link", "链接")` so the footer
  shows the key.
- Calling `action_open_link` invokes `webbrowser.open` with
  `https://polymarket.com/event/{event.slug}` when the slug is present.
- Missing slug / missing event_id → inline notify, no browser call.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event
from polily.core.events import EventBus
from polily.scan_log import ScanLogEntry
from polily.tui.service import PolilyService

# ----------------- Shared fixtures -----------------


@pytest.fixture
def svc_with_slug(tmp_path):
    cfg = MagicMock()
    cfg.tui.heartbeat_seconds = 5.0  # Phase 0 Task 14: real float for Textual timer
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "s.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test Event", slug="test-event-slug", updated_at="now"),
        db,
    )
    yield PolilyService(config=cfg, db=db, event_bus=EventBus())
    db.close()


@pytest.fixture
def svc_no_slug(tmp_path):
    cfg = MagicMock()
    cfg.tui.heartbeat_seconds = 5.0  # Phase 0 Task 14: real float for Textual timer
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "s.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test Event", slug=None, updated_at="now"),
        db,
    )
    yield PolilyService(config=cfg, db=db, event_bus=EventBus())
    db.close()


# ----------------- ScoreResultView -----------------


async def test_score_result_has_o_open_link_binding(svc_with_slug):
    from polily.tui.views.score_result import ScoreResultView

    keys = {b.key for b in ScoreResultView.BINDINGS}
    assert "o" in keys, f"`o` binding missing on ScoreResultView. Keys: {keys}"


async def test_score_result_o_opens_polymarket_url(svc_with_slug):
    from polily.tui.app import PolilyApp
    from polily.tui.views.score_result import ScoreResultView

    app = PolilyApp(service=svc_with_slug)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScoreResultView(event_id="ev1", service=svc_with_slug)
        await app.mount(view)
        await pilot.pause()
        with patch("webbrowser.open") as mock_open:
            view.action_open_link()
        mock_open.assert_called_once_with(
            "https://polymarket.com/event/test-event-slug",
        )


async def test_score_result_o_without_slug_notifies(svc_no_slug, monkeypatch):
    from polily.tui.app import PolilyApp
    from polily.tui.views.score_result import ScoreResultView

    app = PolilyApp(service=svc_no_slug)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScoreResultView(event_id="ev1", service=svc_no_slug)
        await app.mount(view)
        await pilot.pause()
        notify_calls: list = []
        monkeypatch.setattr(view, "notify", lambda msg, **kw: notify_calls.append((msg, kw)))
        with patch("webbrowser.open") as mock_open:
            view.action_open_link()
        mock_open.assert_not_called()
        assert notify_calls, "expected a notify() when slug missing"


# ----------------- ScanLogDetailView -----------------


def _entry(event_id: str | None) -> ScanLogEntry:
    return ScanLogEntry(
        scan_id="s1",
        type="analyze",
        event_id=event_id,
        market_title="Test Event",
        started_at="2026-04-21T10:00:00+00:00",
        finished_at="2026-04-21T10:01:00+00:00",
        total_elapsed=60.0,
        status="completed",
        trigger_source="manual",
    )


async def test_scan_log_detail_has_o_open_link_binding(svc_with_slug):
    from polily.tui.views.scan_log import ScanLogDetailView

    keys = {b.key for b in ScanLogDetailView.BINDINGS}
    assert "o" in keys, f"`o` binding missing on ScanLogDetailView. Keys: {keys}"


async def test_scan_log_detail_o_opens_polymarket_url(svc_with_slug):
    from polily.tui.app import PolilyApp
    from polily.tui.views.scan_log import ScanLogDetailView

    app = PolilyApp(service=svc_with_slug)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogDetailView(_entry("ev1"), db=svc_with_slug.db)
        await app.mount(view)
        await pilot.pause()
        with patch("webbrowser.open") as mock_open:
            view.action_open_link()
        mock_open.assert_called_once_with(
            "https://polymarket.com/event/test-event-slug",
        )


async def test_scan_log_detail_o_without_event_id_notifies(svc_with_slug, monkeypatch):
    from polily.tui.app import PolilyApp
    from polily.tui.views.scan_log import ScanLogDetailView

    app = PolilyApp(service=svc_with_slug)
    app._restart_daemon = lambda: None
    async with app.run_test() as pilot:
        await pilot.pause()
        view = ScanLogDetailView(_entry(None), db=svc_with_slug.db)
        await app.mount(view)
        await pilot.pause()
        notify_calls: list = []
        monkeypatch.setattr(view, "notify", lambda msg, **kw: notify_calls.append((msg, kw)))
        with patch("webbrowser.open") as mock_open:
            view.action_open_link()
        mock_open.assert_not_called()
        assert notify_calls, "expected a notify() when event_id missing"
