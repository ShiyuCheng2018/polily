"""Parse config_docs/*.<lang>.md → dict[key_path, html_description].

v0.10.x — i18n: each docs file has a language suffix (`movement.en.md` /
`movement.zh.md`). `load_all(lang)` reads the requested language; if a
particular file lacks a translation for that lang, it falls back to the
`*.en.md` canonical so users see content (in en) instead of a missing
description. CI gate `tests/test_config_docs_i18n_parity.py` enforces
that every file has both `.en.md` and `.zh.md` companions in shipped
code, so the fallback is only meaningful for hypothetical new languages
that haven't been translated yet.

`polily.core.*` is intentionally framework-free — the language is a
parameter, not pulled from `polily.tui.i18n`. The TUI modal call sites
pass `current_language()` in.
"""
from __future__ import annotations

import re
from pathlib import Path

# Section header that mints a new key block: `## <key_path>` where key_path
# starts with a letter (so `## _signals_glossary` is skipped).
_SECTION_RE = re.compile(r"^##\s+(?P<key>[a-zA-Z][\w.]*)\s*$")

# Underscore-prefix `## _name` sections — used by the cross-reference glossary
# (`## _signals_glossary`). Captured here so `load_signals_glossary` can find
# the boundary; `parse_markdown` continues to skip them entirely.
_UNDERSCORE_SECTION_RE = re.compile(r"^##\s+_(?P<name>\w+)\s*$")

# Sub-heading inside a section: `### signal_name` — used to enumerate entries
# in the signals glossary.
_SUBSECTION_RE = re.compile(r"^###\s+(?P<name>\w+)\s*$")

_DOCS_DIR = Path(__file__).parent

# en is the canonical fallback (polily ships in English by default; zh is
# a localized override). New languages opt in by adding `<base>.<lang>.md`;
# missing translations degrade to en rather than displaying nothing.
_FALLBACK_LANG = "en"


def parse_markdown(path: Path) -> dict[str, str]:
    """Parse one .md file. Returns {key_path: description_markdown_text}.

    Sections starting with `_` are excluded — they're cross-references
    (signals glossary) consumed by anchor links, not directly displayed.
    """
    sections: dict[str, str] = {}
    current_key: str | None = None
    current_lines: list[str] = []

    for line in path.read_text(encoding="utf-8").splitlines():
        match = _SECTION_RE.match(line)
        if match:
            # Flush the previous block before opening the next.
            if current_key is not None:
                sections[current_key] = "\n".join(current_lines).strip()
            current_key = match.group("key")
            current_lines = []
        elif current_key is not None:
            current_lines.append(line)

    # Final block.
    if current_key is not None:
        sections[current_key] = "\n".join(current_lines).strip()

    return sections


def _bases() -> list[str]:
    """Return the set of doc bases (e.g. 'movement', 'scoring') by
    inspecting `<base>.en.md` files — en is the canonical fallback
    (mandatory in shipped code per CI gate), so it's the authoritative
    source of "what files exist".
    """
    return sorted(
        p.name.removesuffix(f".{_FALLBACK_LANG}.md")
        for p in _DOCS_DIR.glob(f"*.{_FALLBACK_LANG}.md")
        if not p.name.startswith("_")
    )


def _resolve_lang_path(base: str, lang: str) -> Path:
    """Return the path to load for (base, lang) with fallback.

    Tries `<base>.<lang>.md` first; if missing, returns `<base>.<fallback>.md`
    so the caller always reads a real file. Caller is responsible for
    erroring if even the fallback is absent (shouldn't happen in shipped
    code thanks to the parity CI gate).
    """
    primary = _DOCS_DIR / f"{base}.{lang}.md"
    if primary.exists():
        return primary
    return _DOCS_DIR / f"{base}.{_FALLBACK_LANG}.md"


def load_all(lang: str = _FALLBACK_LANG) -> dict[str, str]:
    """Load all section descriptions from polily/core/config_docs/*.<lang>.md.

    Per-base fallback: a missing `<base>.<lang>.md` falls back to
    `<base>.zh.md` (canonical). Empty `lang` is treated as the fallback.
    """
    if not lang:
        lang = _FALLBACK_LANG
    docs: dict[str, str] = {}
    for base in _bases():
        docs.update(parse_markdown(_resolve_lang_path(base, lang)))
    return docs


def _parse_signals_glossary(path: Path) -> dict[str, str]:
    """Extract `### subheading` blocks under `## _signals_glossary`.

    Returns {signal_name: description_markdown}. Returns empty dict if
    the file doesn't contain a `_signals_glossary` section.

    Boundaries:
      - START: `## _signals_glossary` line
      - END: next `## ` line (any subsequent section) OR EOF
      - WITHIN: each `### name` mints a new sub-block; lines accumulate
        into the current block until the next `###` or section end.
    """
    glossary: dict[str, str] = {}
    in_glossary = False
    current_name: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        if current_name is not None:
            glossary[current_name] = "\n".join(current_lines).strip()

    for line in path.read_text(encoding="utf-8").splitlines():
        # Detect boundary between glossary and other sections.
        if _UNDERSCORE_SECTION_RE.match(line):
            match = _UNDERSCORE_SECTION_RE.match(line)
            assert match is not None
            if match.group("name") == "signals_glossary":
                # Entering the glossary; flush any prior buffer.
                _flush()
                in_glossary = True
                current_name = None
                current_lines = []
                continue
            # Some other underscore section — leave glossary if we were in it.
            if in_glossary:
                _flush()
                in_glossary = False
                current_name = None
                current_lines = []
            continue
        if _SECTION_RE.match(line):
            # Regular `## key.path` ends the glossary block.
            if in_glossary:
                _flush()
                in_glossary = False
                current_name = None
                current_lines = []
            continue
        if in_glossary:
            sub_match = _SUBSECTION_RE.match(line)
            if sub_match:
                _flush()
                current_name = sub_match.group("name")
                current_lines = []
            elif current_name is not None:
                current_lines.append(line)

    # EOF — flush whatever was open.
    if in_glossary:
        _flush()

    return glossary


def load_signals_glossary(lang: str = _FALLBACK_LANG) -> dict[str, str]:
    """Load the `_signals_glossary` section from every config_docs/*.<lang>.md.

    Returns {signal_name: markdown_description}. Used by the
    `WeightFamilyEditModal` to render a collapsible "信号术语速查" /
    "Signal Glossary" block — only entries whose name matches a leaf in
    the family being edited are shown, so crypto/magnitude shows
    `price_z_score` etc. but not `sustained_drift` (which only appears
    in political).

    Per-base fallback to zh, mirroring `load_all`.

    Aggregating across all files is forward-compatible: if a future doc
    file (e.g. `mispricing.<lang>.md`) adds its own `## _signals_glossary`,
    those entries fold in. Today only `movement.<lang>.md` defines one.
    """
    if not lang:
        lang = _FALLBACK_LANG
    glossary: dict[str, str] = {}
    for base in _bases():
        glossary.update(_parse_signals_glossary(_resolve_lang_path(base, lang)))
    return glossary
