"""v0.8.0 Opt-CSS wave 1: new utility classes added to tokens.tcss."""
from pathlib import Path


def test_tokens_has_new_padding_directional_utilities():
    content = Path("scanner/tui/css/tokens.tcss").read_text()
    for token in (".pt-sm", ".pt-md", ".pb-sm", ".pb-md"):
        assert token in content, f"{token} utility class missing"


def test_tokens_py_sm_and_py_md_are_distinct():
    """Regression: .py-sm and .py-md used to both = padding 1;1 (dupe)."""
    import re
    content = Path("scanner/tui/css/tokens.tcss").read_text()
    # Extract each rule block
    py_sm_match = re.search(r"\.py-sm\s*{([^}]+)}", content)
    py_md_match = re.search(r"\.py-md\s*{([^}]+)}", content)
    assert py_sm_match is not None
    assert py_md_match is not None
    assert py_sm_match.group(1).strip() != py_md_match.group(1).strip(), \
        "py-sm and py-md must have distinct values (not duplicates)"


def test_tokens_has_alignment_utilities():
    content = Path("scanner/tui/css/tokens.tcss").read_text()
    for token in (".center", ".text-center", ".text-left", ".text-right"):
        assert token in content, f"alignment utility {token} missing"


def test_tokens_has_bold_dim():
    content = Path("scanner/tui/css/tokens.tcss").read_text()
    assert ".bold" in content
    assert ".dim" in content
