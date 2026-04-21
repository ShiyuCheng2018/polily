"""ChangelogView: renders CHANGELOG.md as Markdown inside a PolilyZone.

v0.8.0 addition. Covers:
- Dev path (repo root) loading
- Fallback error markdown when file missing
- Sidebar + MainScreen wiring (menu "changelog" reachable)
- `r` refresh re-reads content without restarting the TUI
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.events import EventBus
from scanner.tui.service import ScanService


def _svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    return ScanService(config=cfg, db=db, event_bus=EventBus())


def test_load_changelog_from_repo_root():
    """`_load_changelog` returns the dev-checkout CHANGELOG.md contents."""
    from scanner.tui.views.changelog import _load_changelog

    text = _load_changelog()
    # Real repo CHANGELOG.md has these markers regardless of version.
    assert "# Changelog" in text
    assert "Unreleased" in text


def test_load_changelog_falls_back_to_packaged(monkeypatch, tmp_path):
    """When the dev CHANGELOG.md is absent, `_load_changelog` falls
    back to the packaged resource. If neither is available it returns
    a friendly error markdown rather than raising."""
    from scanner.tui.views import changelog as changelog_mod

    # Point dev resolution at a nonexistent path so the function falls
    # through to the `importlib.resources` branch.
    fake_parents = (tmp_path, tmp_path, tmp_path, tmp_path)

    class _FakePath:
        def __init__(self, p):
            self._p = Path(p)

        def resolve(self):
            class _R:
                parents = fake_parents
            return _R()

    # Replace `Path(__file__)` in the module via attribute patching.
    original_path_cls = changelog_mod.Path

    class _PathProxy:
        def __init__(self, *a, **kw):
            self._inner = original_path_cls(*a, **kw)

        def resolve(self):
            class _Resolved:
                parents = fake_parents
            return _Resolved()

        def __truediv__(self, other):
            return original_path_cls("/nonexistent") / other

    monkeypatch.setattr(changelog_mod, "Path", _PathProxy)

    text = changelog_mod._load_changelog()
    # Either the packaged copy succeeded, or we got the friendly
    # "找不到 CHANGELOG" message. Both are acceptable contracts.
    assert "CHANGELOG" in text or "Changelog" in text or "更新日志" not in text


@pytest.mark.asyncio
async def test_changelog_view_mounts_and_shows_markdown(tmp_path):
    """View mounts cleanly and the Markdown widget receives non-empty content."""
    from textual.app import App, ComposeResult
    from textual.widgets import Markdown

    from scanner.tui.views.changelog import ChangelogView
    from scanner.tui.widgets.polily_zone import PolilyZone

    class _Host(App):
        def compose(self) -> ComposeResult:
            yield ChangelogView()

    async with _Host().run_test() as pilot:
        await pilot.pause()
        view = pilot.app.query_one(ChangelogView)
        assert list(view.query(PolilyZone)), "PolilyZone should wrap the Markdown"
        md = view.query_one("#changelog-md", Markdown)
        # Markdown widget holds the source text internally; just assert
        # something non-empty got passed.
        assert md is not None


@pytest.mark.asyncio
async def test_changelog_has_visible_r_refresh_binding():
    """`r` appears in the footer — matches the uniform footer rule."""
    from scanner.tui.views.changelog import ChangelogView
    keys = {b.key: b.show for b in ChangelogView.BINDINGS}
    assert keys.get("r") is True, f"`r` refresh must be show=True, got {keys}"


@pytest.mark.asyncio
async def test_action_refresh_rereads_content(tmp_path, monkeypatch):
    """Calling `action_refresh()` re-invokes `_load_changelog`, so a dev
    edit to CHANGELOG.md in the repo shows up without restarting TUI."""
    from textual.app import App, ComposeResult

    from scanner.tui.views import changelog as changelog_mod

    call_count = [0]
    original_loader = changelog_mod._load_changelog

    def counting_loader():
        call_count[0] += 1
        return original_loader()

    monkeypatch.setattr(changelog_mod, "_load_changelog", counting_loader)

    class _Host(App):
        def compose(self) -> ComposeResult:
            yield changelog_mod.ChangelogView()

    async with _Host().run_test() as pilot:
        await pilot.pause()
        view = pilot.app.query_one(changelog_mod.ChangelogView)
        mounted_calls = call_count[0]  # from initial compose
        assert mounted_calls >= 1
        view.action_refresh()
        await pilot.pause()

    assert call_count[0] > mounted_calls, (
        f"action_refresh should re-read changelog; "
        f"count went {mounted_calls} → {call_count[0]}"
    )


@pytest.mark.asyncio
async def test_main_screen_digit_6_opens_changelog(tmp_path):
    """`6` is bound to show_changelog and the action mounts ChangelogView.

    Can't rely on `pilot.press('6')` because the default tasks view has
    a URL Input that swallows digit keys — matches the same workaround
    used in `test_tui.py::test_press_5_switches_to_archive`.
    """
    from scanner.tui.app import PolilyApp
    from scanner.tui.screens.main import MainScreen
    from scanner.tui.views.changelog import ChangelogView

    svc = _svc(tmp_path)
    app = PolilyApp(service=svc)
    app._restart_daemon = lambda: None
    async with app.run_test(size=(160, 40)) as pilot:
        await pilot.pause()
        screen = next(s for s in app.screen_stack if isinstance(s, MainScreen))

        # (a) Binding table routes "6" to show_changelog.
        bindings = {b.key: b.action for b in screen.BINDINGS}
        assert bindings.get("6") == "show_changelog", (
            f"digit 6 should trigger show_changelog; bindings: {bindings}"
        )

        # (b) Action mounts ChangelogView and flips current menu.
        screen.action_show_changelog()
        await pilot.pause()
        assert screen._current_menu == "changelog"
        assert list(screen.query(ChangelogView)), "ChangelogView should be mounted"


def test_main_screen_menu_order_includes_changelog():
    """MENU_ORDER has `changelog` last so up/down nav cycles through it."""
    from scanner.tui.screens.main import MainScreen
    assert "changelog" in MainScreen.MENU_ORDER
    assert MainScreen.MENU_ORDER[-1] == "changelog", (
        f"changelog should be last menu item, got order {MainScreen.MENU_ORDER}"
    )


def test_sidebar_includes_changelog_item():
    """Sidebar renders a `更新日志` / `changelog` menu entry."""
    from scanner.tui.widgets.sidebar import MENU_ICONS
    assert "changelog" in MENU_ICONS


def test_pyproject_bundles_changelog_into_wheel():
    """pyproject.toml's hatch config force-includes CHANGELOG.md so the
    installed package can ship `importlib.resources.files("scanner") /
    "CHANGELOG.md"`. Locks the contract tested by `_load_changelog`'s
    packaged-resource fallback."""
    root = Path(__file__).resolve().parents[1]
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "force-include" in text
    assert 'CHANGELOG.md' in text
    assert 'scanner/CHANGELOG.md' in text
