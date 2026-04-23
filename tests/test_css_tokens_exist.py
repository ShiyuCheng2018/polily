# tests/test_css_tokens_exist.py
"""v0.8.0 Task 2: spacing + typography utility classes must exist."""
from pathlib import Path


def test_tokens_css_exists():
    p = Path("polily/tui/css/tokens.tcss")
    assert p.exists(), "tokens.tcss missing — design system cannot load"


def test_tokens_has_spacing_classes():
    content = Path("polily/tui/css/tokens.tcss").read_text()
    for token in (".p-xs", ".p-sm", ".p-md", ".p-lg", ".p-xl"):
        assert token in content, f"{token} utility class missing"


def test_tokens_has_typography_classes():
    content = Path("polily/tui/css/tokens.tcss").read_text()
    for cls in (".h1", ".h2", ".h3", ".body", ".caption", ".code"):
        assert cls in content, f"{cls} typography class missing"
