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
    cfg.tui.heartbeat_seconds = 5.0  # Phase 0 Task 14: TuiConfig field — Textual timer requires real float
    cfg.tui.language = "zh"  # autouse i18n fixture sets active lang to zh; pin the cfg side too so PolilyApp._init_i18n_from_prefs doesn't re-init to MagicMock
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
async def test_main_screen_refreshes_sidebar_on_position_or_wallet_update(svc, monkeypatch):
    """Regression for Bug #2: daemon-side auto-resolution writes positions/
    wallet_transactions without publishing on the TUI's bus. The 5s heartbeat
    republishes TOPIC_POSITION_UPDATED / TOPIC_WALLET_UPDATED on the TUI
    bus, and MainScreen must route those to refresh_sidebar_counts so the
    '持仓 (N)' badge stops going stale.

    We verify the routing by spying on dispatch_to_ui inside the main-screen
    module — the bus handler calls `dispatch_to_ui(self.app, self.refresh_
    sidebar_counts)` synchronously on publish, so a spy catches both the
    intent (target function is refresh_sidebar_counts) and the trigger.
    Going end-to-end through Textual's scheduler introduces timing
    flakiness unrelated to the fix.
    """
    from polily.core.events import TOPIC_POSITION_UPDATED, TOPIC_WALLET_UPDATED
    from polily.tui import screens
    from polily.tui.app import PolilyApp
    from polily.tui.screens.main import MainScreen

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None

    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        screen = next(
            (s for s in app.screen_stack if isinstance(s, MainScreen)), None,
        )
        assert screen is not None, "MainScreen must be on the screen stack"

        dispatched: list[tuple] = []

        def spy(target_app, fn) -> None:
            dispatched.append((target_app, fn))

        monkeypatch.setattr(screens.main, "dispatch_to_ui", spy)

        svc.event_bus.publish(TOPIC_POSITION_UPDATED, {"source": "heartbeat"})
        assert len(dispatched) == 1, (
            f"POSITION_UPDATED must route through dispatch_to_ui; got {dispatched}"
        )
        assert dispatched[0][1] == screen.refresh_sidebar_counts, (
            "dispatch target must be refresh_sidebar_counts"
        )

        svc.event_bus.publish(TOPIC_WALLET_UPDATED, {"source": "heartbeat"})
        assert len(dispatched) == 2, (
            f"WALLET_UPDATED must route through dispatch_to_ui; got {dispatched}"
        )
        assert dispatched[1][1] == screen.refresh_sidebar_counts


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
    """All menu entries present in expected order.

    v0.12.0 inserted `strategy` before `changelog`.
    v0.12.x appended `companions` after `changelog` (polily-plugin promo
    surface — see tests/tui/test_companions_view.py).
    """
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.sidebar import Sidebar, SidebarItem

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        sidebar = app.screen.query_one(Sidebar)
        menu_ids = [item.menu_id for item in sidebar.query(SidebarItem)]
        assert menu_ids == [
            "tasks", "monitor", "paper", "wallet", "history",
            "archive", "config", "strategy", "changelog", "companions",
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


# ---------------------------------------------------------------------------
# v0.11.4 review fix CR-1: MainScreen.on_mount must NOT block on PyPI fetch.
# Pre-fix: should_show_update_star() ran synchronously on the mount thread,
# so a cache-miss (every fresh install + every 6h cache expiry) would freeze
# the TUI for up to 5s while httpx awaited PyPI. Must be dispatched to a
# worker thread.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_check_runs_in_worker_not_main_thread(svc, monkeypatch):
    """Regression CR-1: should_show_update_star must run off the mount thread.

    Captures the thread name at the call site. Pre-fix, the call ran
    inline on the same thread that executed `on_mount` (i.e., the main
    asyncio loop's thread, named 'MainThread' or similar). Post-fix, it
    runs in a `run_worker(thread=True)` worker, which Textual names
    differently (something like 'AppWorker' / a non-main thread).
    """
    import threading

    from polily.core import update_check
    from polily.tui.app import PolilyApp

    captured_threads: list[str] = []
    main_thread_name = threading.current_thread().name

    def spy_should_show(db, *_a, **_kw):
        captured_threads.append(threading.current_thread().name)
        return False  # don't actually mark — just observe the thread

    monkeypatch.setattr(
        update_check, "should_show_update_star", spy_should_show,
    )

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        # Wait for any worker thread to land
        for _ in range(20):
            await pilot.pause()
            if captured_threads:
                break

    assert captured_threads, (
        "should_show_update_star was never called — on_mount must dispatch "
        "the update check (in a worker thread)"
    )

    # All recorded calls must be off the main thread
    for tname in captured_threads:
        assert tname != main_thread_name, (
            f"should_show_update_star ran on main thread {tname!r} — "
            f"this blocks the TUI on cache-miss network calls. Must be in "
            f"run_worker(thread=True). Captured: {captured_threads}"
        )


@pytest.mark.asyncio
async def test_update_check_marks_sidebar_when_newer_available(svc, monkeypatch):
    """Worker path actually marks the sidebar `*` when check returns True.

    Companion to the thread-isolation test: confirms the worker's
    success path still invokes `sidebar.mark_new_data("changelog")` via
    a UI-thread hop (call_from_thread).
    """
    from polily.core import update_check
    from polily.tui.app import PolilyApp
    from polily.tui.widgets.sidebar import Sidebar

    monkeypatch.setattr(
        update_check, "should_show_update_star", lambda db, *_a, **_kw: True,
    )

    from polily.tui.widgets.sidebar import SidebarItem

    def _changelog_item(_app):
        for item in _app.screen.query(SidebarItem):
            if item.menu_id == "changelog":
                return item
        return None

    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(120, 40)) as pilot:
        # Pump until worker hop has landed and sidebar updates
        item = None
        for _ in range(30):
            await pilot.pause()
            item = _changelog_item(app)
            if item is not None and item._has_new:
                break

        assert item is not None, "changelog SidebarItem should be mounted"
        assert item._has_new, (
            "After worker check returns True, changelog SidebarItem._has_new "
            "must be True (yellow `*` shown via mark_new_data)"
        )

    # silence unused-import warning
    _ = Sidebar
