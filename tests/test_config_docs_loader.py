"""Tests for the markdown loader (design §6.2)."""
from __future__ import annotations

from polily.core.config_docs._loader import (
    load_all,
    load_signals_glossary,
    parse_markdown,
)


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
    """load_all walks polily/core/config_docs/*.<lang>.md (excl. _-prefix files).

    v0.10.x: file naming is `<base>.<lang>.md`; bases discovered via
    `*.en.md` glob (en is the canonical fallback).
    """
    # Point loader at tmp_path
    (tmp_path / "movement.en.md").write_text("## movement.magnitude_threshold\n\nfoo\n", encoding="utf-8")
    (tmp_path / "scoring.en.md").write_text("## scoring.thresholds.tier_a_min_score\n\nbar\n", encoding="utf-8")
    (tmp_path / "_helpers.en.md").write_text("## should_be_ignored\n\nbaz\n", encoding="utf-8")

    monkeypatch.setattr(
        "polily.core.config_docs._loader._DOCS_DIR", tmp_path,
    )

    docs = load_all()
    assert "movement.magnitude_threshold" in docs
    assert "scoring.thresholds.tier_a_min_score" in docs
    assert "should_be_ignored" not in docs


def test_loader_output_contains_default_value_phrase():
    """Every territory A description starts with the per-language default
    phrase: `**Default X.**` (en) / `**默认 X。**` (zh). Convention pin
    so future docs follow."""
    import pytest
    for lang, marker in (("en", "**Default"), ("zh", "**默认")):
        docs = load_all(lang)
        territory_a = [
            (k, v) for k, v in docs.items()
            if k.startswith(("movement.", "scoring.", "mispricing.", "wallet."))
        ]
        no_default_phrase = [k for k, v in territory_a if marker not in v]
        if no_default_phrase:
            pytest.fail(
                f"[{lang}] {len(no_default_phrase)} sections lack `{marker}` phrase:\n"
                + "\n".join(f"  - {k}" for k in sorted(no_default_phrase))
            )


def test_loader_handles_empty_directory(tmp_path, monkeypatch):
    monkeypatch.setattr("polily.core.config_docs._loader._DOCS_DIR", tmp_path)
    assert load_all() == {}


# ---- R4: signals glossary loader (consumer of _signals_glossary section) ----


def test_load_signals_glossary_returns_signal_name_to_description():
    """`_signals_glossary` in `movement.md` defines signal terminology
    used by the WeightFamilyEditModal. Loader returns {signal_name:
    markdown_description}.

    Whis flagged this in R3 — the section was orphan (loader skipped
    `_`-prefix), and R4 is the consumer that finally puts it to work.
    """
    glossary = load_signals_glossary()
    # Production movement.md has 10 signals defined under _signals_glossary
    expected_signals = {
        "price_z_score",
        "book_imbalance",
        "fair_value_divergence",
        "underlying_z_score",
        "cross_divergence",
        "sustained_drift",
        "time_decay_adjusted_move",
        "volume_ratio",
        "trade_concentration",
        "volume_price_confirmation",
    }
    assert expected_signals.issubset(set(glossary.keys())), (
        f"missing signals: {expected_signals - set(glossary.keys())}"
    )


def test_load_signals_glossary_descriptions_are_non_empty():
    """Every entry has a non-empty markdown body (post-strip)."""
    glossary = load_signals_glossary()
    for signal_name, description in glossary.items():
        assert description.strip(), f"{signal_name} has empty body"


def test_load_signals_glossary_extracts_subsections_under_glossary_only(
    tmp_path, monkeypatch,
):
    """Only `### name` headings nested under `## _signals_glossary` are
    returned — `### name` under another `## key` (regular section) is
    NOT confused into the glossary.
    """
    md = """\
## _signals_glossary

### foo
foo description

### bar
bar description

## movement.something

### should_not_appear
this is a sub-heading inside a regular section, not the glossary
"""
    (tmp_path / "movement.en.md").write_text(md, encoding="utf-8")
    monkeypatch.setattr(
        "polily.core.config_docs._loader._DOCS_DIR", tmp_path,
    )

    glossary = load_signals_glossary()
    assert set(glossary.keys()) == {"foo", "bar"}
    assert "foo description" in glossary["foo"]
    assert "bar description" in glossary["bar"]


def test_load_signals_glossary_returns_empty_when_no_glossary_section(
    tmp_path, monkeypatch,
):
    """Defensive: doc without a `_signals_glossary` section → empty dict."""
    md = """\
## movement.some_knob

description without any glossary
"""
    (tmp_path / "movement.en.md").write_text(md, encoding="utf-8")
    monkeypatch.setattr(
        "polily.core.config_docs._loader._DOCS_DIR", tmp_path,
    )

    assert load_signals_glossary() == {}
