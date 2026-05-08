"""default.md content sanity checks."""
from pathlib import Path

import polily


def test_default_md_has_four_sections():
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert len(headings) == 4, f"Expected 4 H2 sections, got {len(headings)}: {headings}"


def test_default_md_contains_five_self_reflective_questions():
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    for q in ("Q1.", "Q2.", "Q3.", "Q4.", "Q5."):
        assert q in text, f"Default strategy missing self-reflective {q}"


def test_default_md_mentions_has_position():
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    assert "has_position" in text


def test_default_md_is_english_no_chinese():
    """Per Q1: agent prompts ship as English; user_lang directive switches output language."""
    text = (Path(polily.__file__).parent / "strategies" / "default.md").read_text(encoding="utf-8")
    cjk = [c for c in text if "一" <= c <= "鿿"]
    assert cjk == [], f"default.md must be English; found CJK chars: {set(cjk)}"
