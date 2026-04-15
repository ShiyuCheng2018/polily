"""Smoke tests for TUI: startup, navigation, basic interactions."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scanner.tui.app import PolilyApp
from scanner.tui.service import ScanService


def _mock_service():
    """Create a ScanService with pre-loaded mock data (v0.5.0 DB-first API)."""
    service = ScanService.__new__(ScanService)
    service.config = MagicMock()
    service.config.paper_trading.default_position_size_usd = 20
    service.config.paper_trading.assumed_round_trip_friction_pct = 0.04
    service.config.archiving.db_file = "/tmp/test_polily.db"
    import tempfile

    from scanner.core.db import PolilyDB
    _tmp = tempfile.TemporaryDirectory()
    service._tmp_dir = _tmp  # prevent GC cleanup during test
    service.db = PolilyDB(Path(_tmp.name) / "polily.db")
    service.total_scanned = 0
    service.on_progress = None
    service._steps = []
    service._current_log = None
    service.last_scan_id = None
    service._current_narrator = None

    return service


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
            # Navigate to research first
            screen._navigate_to("research")
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
