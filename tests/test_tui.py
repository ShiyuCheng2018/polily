"""Smoke tests for TUI: startup, navigation, basic interactions."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scanner.tui.app import PolilyApp
from scanner.tui.service import ScanService


def _mock_service():
    """Create a ScanService for TUI smoke tests.

    Uses the real `__init__` so every new attribute added by future tasks
    (wallet / positions / trade_engine / ...) is wired consistently. Config
    is a MagicMock because TUI tests only need the config *shape*, not real
    loaded values.
    """
    import tempfile

    from scanner.core.db import PolilyDB

    config = MagicMock()
    config.paper_trading.default_position_size_usd = 20
    config.paper_trading.assumed_round_trip_friction_pct = 0.04
    _tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(_tmp.name) / "polily.db")
    service = ScanService(config=config, db=db)
    service._tmp_dir = _tmp  # prevent GC cleanup during test
    return service


def _seed_archived_event(service, event_id: str, title: str, score: float = 80.0):
    """Seed an archived event (closed=1, auto_monitor=1) directly into the DB."""
    from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
    from scanner.core.monitor_store import upsert_event_monitor

    upsert_event(
        EventRow(event_id=event_id, title=title, closed=1,
                 updated_at="2026-04-19T00:00:00"),
        service.db,
    )
    service.db.conn.execute(
        "UPDATE events SET structure_score=? WHERE event_id=?", (score, event_id),
    )
    upsert_market(
        MarketRow(market_id=f"m-{event_id}", event_id=event_id, question="Q",
                  updated_at="2026-04-19T00:00:00"),
        service.db,
    )
    upsert_event_monitor(event_id, auto_monitor=True, db=service.db)
    service.db.conn.commit()


class TestTUIStartup:
    @pytest.mark.asyncio
    async def test_app_starts_without_crash(self):
        """App mounts and renders without crashing."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)):
            assert app.is_running

    @pytest.mark.asyncio
    async def test_app_shows_sidebar(self):
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from scanner.tui.widgets.sidebar import Sidebar
            sidebar = app.screen.query_one(Sidebar)
            assert sidebar is not None


class TestTUINavigation:
    @pytest.mark.asyncio
    async def test_switch_to_research(self):
        """Press 1 to switch to research view."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            await pilot.press("1")
            await pilot.pause()
            assert app.is_running

    @pytest.mark.asyncio
    async def test_switch_to_watchlist(self):
        """Press 2 to switch to watchlist view."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            await pilot.press("2")
            await pilot.pause()
            assert app.is_running

    @pytest.mark.asyncio
    async def test_switch_to_paper(self):
        """Press 3 to switch to paper status view."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            await pilot.press("3")
            await pilot.pause()
            assert app.is_running

    @pytest.mark.asyncio
    async def test_switch_to_tasks(self):
        """Press 0 to switch to task log view."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            await pilot.press("1")
            await pilot.pause()
            await pilot.press("0")
            await pilot.pause()
            assert app.is_running
            assert screen._current_menu == "tasks"


class TestTUIDetailView:
    @pytest.mark.asyncio
    async def test_enter_detail_and_escape_back(self):
        """Enter opens detail, Esc returns to list."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            # Navigate to tasks first (the default "research"-era label before v0.5).
            screen._navigate_to("tasks")
            await pilot.pause()

            await pilot.press("enter")
            await pilot.pause()
            assert app.is_running

            await pilot.press("escape")
            await pilot.pause()
            assert app.is_running


class TestTUIRefreshAndScan:
    @pytest.mark.asyncio
    async def test_refresh_does_not_trigger_scan(self):
        """Press r should re-render current view, not start a new scan."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            await pilot.press("r")
            await pilot.pause()
            assert screen._loading is False
            assert app.is_running

class TestTUIQuit:
    @pytest.mark.asyncio
    async def test_quit(self):
        """Press q to quit."""
        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("q")


class TestTUIArchive:
    """Archive-view integration: sidebar count, menu-5 switch, row → detail.

    Locks in the 'looking back' UX claim from the v0.6.x CHANGELOG: the
    Archive view surfaces closed monitored events, press 5 navigates to it,
    and clicking a row opens that event's EventDetailView for retrospective
    review.
    """

    @pytest.mark.asyncio
    async def test_sidebar_shows_archive_count(self):
        """Seed 2 archived events → sidebar archive item renders '(2)'."""
        from scanner.tui.widgets.sidebar import Sidebar, SidebarItem

        service = _mock_service()
        _seed_archived_event(service, "ev-1", "Event 1")
        _seed_archived_event(service, "ev-2", "Event 2")

        app = PolilyApp(service=service)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            sidebar = app.screen.query_one(Sidebar)
            archive_item = next(
                i for i in sidebar.query(SidebarItem) if i.menu_id == "archive"
            )
            assert archive_item.count == 2
            # The visible text also includes the count suffix.
            assert "(2)" in str(archive_item.render())

    @pytest.mark.asyncio
    async def test_press_5_switches_to_archive(self):
        """Key '5' is bound to show_archive, which mounts ArchivedEventsView.

        The default TUI surface has a URL `Input` that eats digit keys, so
        we can't reliably simulate `pilot.press('5')` without losing the
        keystroke to the input widget. Instead we verify (a) the screen
        binding table includes `5 → show_archive` and (b) that action wires
        up the view correctly. These two together equal "pressing 5 works".
        """
        from scanner.tui.views.archived_events import ArchivedEventsView

        app = PolilyApp(service=_mock_service())
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            # (a) The binding exists and routes key "5" to action_show_archive.
            bindings = {b.key: b.action for b in screen.BINDINGS}
            assert bindings.get("5") == "show_archive"

            # (b) Invoking the action has the expected effect.
            screen.action_show_archive()
            await pilot.pause()

            assert screen._current_menu == "archive"
            content = screen.query_one("#content-area")
            archive_views = list(content.query(ArchivedEventsView))
            assert len(archive_views) == 1

    @pytest.mark.asyncio
    async def test_view_archived_detail_message_opens_event_detail(self):
        """Posting ViewArchivedDetail → EventDetailView replaces content."""
        from scanner.tui.views.archived_events import ViewArchivedDetail
        from scanner.tui.views.event_detail import EventDetailView

        service = _mock_service()
        _seed_archived_event(service, "ev-archived", "Archived title")

        app = PolilyApp(service=service)
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            # Switch to archive first (establishes realistic starting state).
            await pilot.press("5")
            await pilot.pause()

            # Simulate a row-click by posting the message directly (the view
            # itself posts this from on_data_table_row_selected / action_view_detail).
            screen.post_message(ViewArchivedDetail("ev-archived"))
            await pilot.pause()

            content = screen.query_one("#content-area")
            detail_views = list(content.query(EventDetailView))
            assert len(detail_views) == 1
            assert detail_views[0].event_id == "ev-archived"
