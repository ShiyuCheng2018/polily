# tests/test_polily_theme.py
"""Polily brand themes: registration + default selection.

v0.8.0 added polily-dark as default. v0.12.0 flipped the default to
polily-geek (phosphor-green). polily-dark remains registered and
selectable via Ctrl+P → Change theme; existing users keep whatever
they previously selected (Textual persists theme).
"""
from polily.tui.app import PolilyApp


async def test_polily_geek_is_registered_and_default():
    """v0.12.0+ default — phosphor-green is the first impression for new installs."""
    app = PolilyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "polily-geek" in app.available_themes, \
            f"polily-geek not registered. Available: {list(app.available_themes)}"
        assert app.theme == "polily-geek", \
            f"polily-geek not default in v0.12.0+. Active: {app.theme}"


async def test_builtin_themes_still_available():
    """User can still Ctrl+P to switch to built-in themes."""
    app = PolilyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for name in ("textual-dark", "nord", "dracula"):
            assert name in app.available_themes, f"built-in {name} missing"


async def test_polily_dark_is_registered_but_not_default():
    """polily-dark stays available for users who prefer the v0.8.0 look,
    but is no longer the default in v0.12.0+."""
    app = PolilyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "polily-dark" in app.available_themes, \
            f"polily-dark not registered. Available: {list(app.available_themes)}"
        assert app.theme != "polily-dark", "dark should not be default in v0.12.0+"
        # And verify we can switch to it
        app.theme = "polily-dark"
        await pilot.pause()
        assert app.theme == "polily-dark"
