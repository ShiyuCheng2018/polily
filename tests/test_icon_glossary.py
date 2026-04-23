# tests/test_icon_glossary.py
"""v0.8.0 Task 11: verify all icon constants live in Nerd Font range."""
import polily.tui.icons as icons


def test_all_icon_constants_are_in_nerd_font_range():
    """Nerd Font glyphs use Unicode Private Use Area: U+E000–U+F8FF."""
    for name in dir(icons):
        if not name.startswith("ICON_"):
            continue
        val = getattr(icons, name)
        assert isinstance(val, str) and len(val) == 1, \
            f"{name} must be a single character, got {val!r}"
        cp = ord(val)
        assert 0xE000 <= cp <= 0xF8FF, \
            f"{name} = U+{cp:04X} is outside Nerd Font PUA range"


def test_status_icons_map_covers_all_scan_log_statuses():
    """STATUS_ICONS must cover every scan_logs.status enum value."""
    required = {"pending", "running", "completed", "failed", "cancelled", "superseded"}
    missing = required - set(icons.STATUS_ICONS.keys())
    assert not missing, f"STATUS_ICONS missing: {missing}"
