"""CI gate: every config_docs file ships in zh + en with identical key sets.

Sister to `tests/test_i18n.py::test_bundled_catalogs_have_consistent_key_sets`
— catalog parity catches missing TUI strings; this catches missing knob
descriptions. Without it, switching to English would leave some leaves
showing the zh fallback (or worse, an empty modal description) and
nothing in the build would warn us.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from polily.core.config_docs._loader import (
    _DOCS_DIR,
    load_signals_glossary,
    parse_markdown,
)

# zh is the canonical default per CLAUDE.md; en is the second bundled
# language. Adding a new language is opt-in: drop a `<base>.<lang>.md`
# alongside the others. To enforce it has parity too, append the lang
# code to this list.
_BUNDLED_LANGS = ("zh", "en")


def _bases() -> list[str]:
    return sorted(
        p.name.removesuffix(".en.md")
        for p in _DOCS_DIR.glob("*.en.md")
        if not p.name.startswith("_")
    )


def test_every_doc_file_has_companions_for_every_bundled_lang():
    """Each `<base>.en.md` must have a `<base>.<lang>.md` for every
    bundled language. Catches "translated movement.en.md but forgot
    scoring.en.md" before merge."""
    bases = _bases()
    assert bases, "no *.en.md doc files found — the docs dir was emptied?"
    missing: list[str] = []
    for base in bases:
        for lang in _BUNDLED_LANGS:
            path = _DOCS_DIR / f"{base}.{lang}.md"
            if not path.exists():
                missing.append(path.name)
    if missing:
        pytest.fail(
            f"missing {len(missing)} doc file(s): {sorted(missing)}. "
            f"Each base must ship in all {_BUNDLED_LANGS} languages."
        )


@pytest.mark.parametrize("base", _bases())
def test_zh_and_en_have_identical_section_keys(base: str):
    """`## key.path` sections in `<base>.en.md` must match those in
    `<base>.en.md` exactly. Otherwise the user sees blank descriptions
    after F2 toggling (or unintended fallback to zh)."""
    per_lang: dict[str, set[str]] = {}
    for lang in _BUNDLED_LANGS:
        path = _DOCS_DIR / f"{base}.{lang}.md"
        per_lang[lang] = set(parse_markdown(path).keys())

    reference = per_lang[_BUNDLED_LANGS[0]]
    for lang, keys in per_lang.items():
        if keys == reference:
            continue
        diff_only_here = sorted(keys - reference)
        diff_missing_here = sorted(reference - keys)
        pytest.fail(
            f"{base}: key set mismatch between {_BUNDLED_LANGS[0]} and "
            f"{lang}\n"
            f"  only in {lang}:                 {diff_only_here}\n"
            f"  in {_BUNDLED_LANGS[0]} but missing here: {diff_missing_here}"
        )


def test_signals_glossary_parity_across_languages():
    """The `_signals_glossary` cross-reference (currently in
    movement.<lang>.md) must have the same `### name` entries across
    languages. WeightFamilyEditModal pulls from this — a missing entry
    would render as "*(no glossary entries)*" placeholder for that
    signal under one language but not the other."""
    per_lang: dict[str, set[str]] = {
        lang: set(load_signals_glossary(lang).keys())
        for lang in _BUNDLED_LANGS
    }
    reference = per_lang[_BUNDLED_LANGS[0]]
    for lang, keys in per_lang.items():
        assert keys == reference, (
            f"signals_glossary key mismatch in {lang}: "
            f"only-here={sorted(keys - reference)}, "
            f"missing-here={sorted(reference - keys)}"
        )


def test_loader_falls_back_to_en_when_lang_file_missing(tmp_path: Path):
    """A loader call for a non-bundled language (e.g. 'ja') must
    transparently fall back to en (canonical) — not crash, not return empty."""
    # Use real docs dir; just ask for a language we know isn't bundled.
    from polily.core.config_docs import load_all
    en_docs = load_all("en")
    ja_docs = load_all("ja")  # not bundled
    assert ja_docs == en_docs, (
        "load_all('ja') must fall back to en wholesale (no per-base mixing "
        "for an unbundled language)"
    )
