"""Smoke tests for TUI: startup, navigation, basic interactions."""

from unittest.mock import MagicMock

import pytest

from scanner.mispricing import MispricingResult
from scanner.reporting import ScoredCandidate, TierResult
from scanner.scoring import ScoreBreakdown
from scanner.tui.app import PolilyApp
from scanner.tui.service import ScanService
from tests.conftest import make_market


def _mock_service():
    """Create a ScanService with pre-loaded mock data."""
    service = ScanService.__new__(ScanService)
    service.config = MagicMock()
    service.config.paper_trading.data_file = ":memory:"
    service.config.paper_trading.default_position_size_usd = 20
    service.config.paper_trading.assumed_round_trip_friction_pct = 0.04
    service.config.archiving.scan_log_file = "/tmp/test_scan_logs.json"
    service.config.archiving.scan_log_max_entries = 30
    service.total_scanned = 100
    service.on_progress = None
    service._steps = []
    service._current_log = None
    service.last_scan_id = None

    c1 = ScoredCandidate(
        market=make_market(market_id="m1", title="BTC above $88K?", yes_price=0.55),
        score=ScoreBreakdown(20, 18, 16, 12, 8, total=74),
        mispricing=MispricingResult(signal="moderate", direction="underpriced",
                                     theoretical_fair_value=0.65, deviation_pct=0.10,
                                     details="模型估值 0.65, 市价 0.55"),
    )
    c2 = ScoredCandidate(
        market=make_market(market_id="m2", title="CPI exceed 3.5%?", yes_price=0.50),
        score=ScoreBreakdown(15, 14, 12, 10, 6, total=57),
        mispricing=MispricingResult(signal="none"),
    )

    service.tiers = TierResult(tier_a=[c1], tier_b=[c2], tier_c=[])
    service.get_research = lambda: [c1]
    service.get_watchlist = lambda: [c2]
    service.get_paper_trades = lambda: []
    service.get_scan_logs = lambda: []
    service.get_paper_stats = lambda: {"total_trades": 0, "open": 0, "resolved": 0, "wins": 0, "losses": 0, "win_rate": 0, "total_paper_pnl": 0, "total_friction_adjusted_pnl": 0}
    return service


class TestTUIStartup:
    @pytest.mark.asyncio
    async def test_app_starts_without_crash(self):
        """App mounts and renders without crashing."""
        app = PolilyApp()
        app.service = _mock_service()
        async with app.run_test(size=(120, 40)):
            assert app.is_running

    @pytest.mark.asyncio
    async def test_app_shows_sidebar(self):
        app = PolilyApp()
        app.service = _mock_service()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            from scanner.tui.widgets.sidebar import Sidebar
            sidebar = app.screen.query_one(Sidebar)
            assert sidebar is not None


class TestTUINavigation:
    @pytest.mark.asyncio
    async def test_switch_to_research(self):
        """Press 1 to switch to research view."""
        app = PolilyApp()
        app.service = _mock_service()
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
        app = PolilyApp()
        app.service = _mock_service()
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
        app = PolilyApp()
        app.service = _mock_service()
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
        app = PolilyApp()
        app.service = _mock_service()
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
        app = PolilyApp()
        app.service = _mock_service()
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
        app = PolilyApp()
        app.service = _mock_service()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._loading = False
            await pilot.pause()

            await pilot.press("r")
            await pilot.pause()
            assert screen._loading is False
            assert app.is_running

    @pytest.mark.asyncio
    async def test_scan_debounce_while_loading(self):
        """_start_scan returns immediately when _loading is True."""
        app = PolilyApp()
        app.service = _mock_service()
        async with app.run_test(size=(120, 40)):
            screen = app.screen
            screen._loading = True
            # Direct call — _start_scan should bail out immediately
            screen._start_scan()
            assert screen._loading is True

    @pytest.mark.asyncio
    async def test_scan_complete_does_not_auto_navigate(self):
        """Scan complete should NOT auto-navigate to research."""
        app = PolilyApp()
        app.service = _mock_service()
        async with app.run_test(size=(120, 40)) as pilot:
            screen = app.screen
            screen.service = app.service
            screen._current_menu = "paper"
            screen._loading = True

            screen._on_scan_complete()
            await pilot.pause()
            # Should stay on paper, not jump to research
            assert screen._current_menu == "paper"


class TestTUIQuit:
    @pytest.mark.asyncio
    async def test_quit(self):
        """Press q to quit."""
        app = PolilyApp()
        app.service = _mock_service()
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("q")
