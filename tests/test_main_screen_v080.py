"""v0.8.0 Task 32: MainScreen + widgets/cards + widgets/sidebar migrated.

Covers the final Phase 3 fan-out migration: MainScreen, MetricCard/DashPanel
legacy widgets, and Sidebar/SidebarItem (with Nerd Font icons).
"""
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.events import EventBus
from polily.tui.service import PolilyService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "ms.db")
    yield PolilyService(config=cfg, db=db, event_bus=EventBus())
    db.close()


# ----------------------------------------------------------------------
# MainScreen
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_main_screen_mounts_sidebar_and_content(svc):
    """Main screen must have Sidebar + content area."""
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.sidebar import Sidebar

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sidebars = list(app.screen.query(Sidebar))
        assert len(sidebars) == 1, f"expected 1 Sidebar, got {len(sidebars)}"


@pytest.mark.asyncio
async def test_main_screen_menu_digit_shortcuts_preserved(svc):
    """Menu digit shortcuts (0, 1, 2, 3, 4, 5) still bound for navigation."""
    from polily.tui.screens.main import MainScreen

    keys = {b.key for b in MainScreen.BINDINGS}
    # 0 = tasks, 1 = monitor, 2 = paper, 3 = wallet, 4 = history, 5 = archive
    for k in ("0", "1", "2", "3", "4", "5"):
        assert k in keys, f"digit shortcut {k} missing from MainScreen BINDINGS: {keys}"


@pytest.mark.asyncio
async def test_main_screen_has_no_conflicting_global_bindings(svc):
    """MainScreen must NOT redeclare q / ? / escape (Task 9 moved those to App level)."""
    from polily.tui.screens.main import MainScreen

    keys = {b.key for b in MainScreen.BINDINGS}
    for conflict in ("q", "question_mark", "escape"):
        assert conflict not in keys, (
            f"MainScreen binding {conflict!r} conflicts with GLOBAL_BINDINGS; "
            f"found in BINDINGS: {keys}"
        )


@pytest.mark.asyncio
async def test_main_screen_status_bar_mounted(svc):
    """Status bar Static must exist at #status-bar."""
    from textual.widgets import Static

    from polily.tui.app import PolilyApp

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        status_bar = app.screen.query_one("#status-bar", Static)
        assert status_bar is not None


# ----------------------------------------------------------------------
# Sidebar + SidebarItem
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sidebar_items_have_nerd_font_icons(svc):
    """SidebarItem menu entries should show Nerd Font glyphs (not plain emoji)."""
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.sidebar import SidebarItem

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        items = list(app.screen.query(SidebarItem))
        assert len(items) >= 3, f"expected >=3 SidebarItems, got {len(items)}"
        # At least one item should contain a Nerd Font PUA character (U+E000-U+F8FF)
        found_nf = False
        for item in items:
            val = (
                getattr(item, "renderable", None)
                or getattr(item, "content", None)
            )
            s = str(val) if val else ""
            if any(0xE000 <= ord(c) <= 0xF8FF for c in s):
                found_nf = True
                break
        assert found_nf, "no Nerd Font glyph found in SidebarItems"


@pytest.mark.asyncio
async def test_sidebar_menu_order_preserved(svc):
    """All menu entries present in expected order (v0.8.0+: changelog added last)."""
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.sidebar import Sidebar, SidebarItem

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sidebar = app.screen.query_one(Sidebar)
        menu_ids = [item.menu_id for item in sidebar.query(SidebarItem)]
        assert menu_ids == [
            "tasks", "monitor", "paper", "wallet", "history", "archive", "changelog",
        ], f"sidebar menu order changed: {menu_ids}"


@pytest.mark.asyncio
async def test_sidebar_active_menu_highlights_correctly(svc):
    """set_active_menu should mark only one item with -active class."""
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.sidebar import Sidebar, SidebarItem

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sidebar = app.screen.query_one(Sidebar)
        sidebar.set_active_menu("monitor")
        await pilot.pause()
        active = [
            i for i in sidebar.query(SidebarItem) if i.has_class("-active")
        ]
        assert len(active) == 1
        assert active[0].menu_id == "monitor"


# ----------------------------------------------------------------------
# MetricCard + DashPanel — preserved legacy widgets (Q7b)
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metric_card_still_works(svc):
    """MetricCard preserved as legacy widget (Q7b: don't delete)."""
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.cards import MetricCard

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        card = MetricCard("test value")
        await app.screen.mount(card)
        await pilot.pause()
        # Should mount without error; legacy widget preserved
        assert card.is_mounted


@pytest.mark.asyncio
async def test_dash_panel_still_works(svc):
    """DashPanel preserved as legacy widget (Q7b: don't delete)."""
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.cards import DashPanel

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        panel = DashPanel()
        await app.screen.mount(panel)
        await pilot.pause()
        assert panel.is_mounted


def test_cards_css_uses_theme_variables():
    """MetricCard / DashPanel styling must reference theme variables, not
    hardcoded hex colors. Empty allowed, but any color must be a $-prefixed
    theme var."""
    import re

    from polily.tui.widgets.cards import DashPanel, MetricCard

    for cls in (MetricCard, DashPanel):
        css = cls.DEFAULT_CSS or ""
        # No raw hex colors.
        assert not re.search(r"#[0-9A-Fa-f]{3,8}\b", css), (
            f"{cls.__name__}.DEFAULT_CSS contains hardcoded hex color: {css!r}"
        )
