# tests/test_polily_theme.py
"""v0.8.0 Task 3: polily-dark theme registers correctly and is default."""
from scanner.tui.app import PolilyApp


async def test_polily_dark_is_registered_and_default():
    app = PolilyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "polily-dark" in app.available_themes, \
            f"polily-dark not registered. Available: {list(app.available_themes)}"
        assert app.theme == "polily-dark", \
            f"polily-dark not default. Active: {app.theme}"


async def test_builtin_themes_still_available():
    """User can still Ctrl+P to switch to built-in themes."""
    app = PolilyApp()
    async with app.run_test() as pilot:
        await pilot.pause()
        for name in ("textual-dark", "nord", "dracula"):
            assert name in app.available_themes, f"built-in {name} missing"
