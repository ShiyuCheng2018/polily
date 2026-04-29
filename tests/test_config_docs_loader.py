"""Tests for the markdown loader (design §6.2)."""
from __future__ import annotations

from polily.core.config_docs._loader import load_all, parse_markdown


def test_parse_markdown_extracts_key_path_sections(tmp_path):
    md = """\
# 异动触发 (Movement)

This is intro text — not associated with any key.

## movement.magnitude_threshold

**默认 70。** 异动幅度阈值。

## movement.quality_threshold

**默认 60。** 异动质量阈值。
"""
    md_path = tmp_path / "movement.md"
    md_path.write_text(md, encoding="utf-8")

    sections = parse_markdown(md_path)
    assert set(sections.keys()) == {
        "movement.magnitude_threshold",
        "movement.quality_threshold",
    }
    assert "默认 70" in sections["movement.magnitude_threshold"]


def test_parse_markdown_skips_underscore_prefix_sections(tmp_path):
    md = """\
## _signals_glossary

### price_z_score
shared signal definition

## movement.weights.crypto.magnitude.price_z_score

**默认 0.15。** Per-market default rationale.
"""
    md_path = tmp_path / "movement.md"
    md_path.write_text(md, encoding="utf-8")

    sections = parse_markdown(md_path)
    # _signals_glossary excluded; only the actual key_path included
    assert list(sections.keys()) == ["movement.weights.crypto.magnitude.price_z_score"]


def test_load_all_aggregates_all_md_files_in_config_docs(tmp_path, monkeypatch):
    """load_all walks polily/core/config_docs/*.md (excl. _-prefix files)."""
    # Point loader at tmp_path
    (tmp_path / "movement.md").write_text("## movement.magnitude_threshold\n\nfoo\n", encoding="utf-8")
    (tmp_path / "scoring.md").write_text("## scoring.thresholds.tier_a_min_score\n\nbar\n", encoding="utf-8")
    (tmp_path / "_helpers.md").write_text("## should_be_ignored\n\nbaz\n", encoding="utf-8")

    monkeypatch.setattr(
        "polily.core.config_docs._loader._DOCS_DIR", tmp_path,
    )

    docs = load_all()
    assert "movement.magnitude_threshold" in docs
    assert "scoring.thresholds.tier_a_min_score" in docs
    assert "should_be_ignored" not in docs
