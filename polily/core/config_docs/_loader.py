"""Parse config_docs/*.md → dict[key_path, html_description]."""
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


def load_all() -> dict[str, str]:
    """Load all section descriptions from polily/core/config_docs/*.md.

    Skips files whose name starts with `_` (currently no such files,
    but keeps the door open for future _shared.md / _helpers.md without
    polluting the key_path namespace).
    """
    docs: dict[str, str] = {}
    for md_path in sorted(_DOCS_DIR.glob("*.md")):
        if md_path.name.startswith("_"):
            continue
        docs.update(parse_markdown(md_path))
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


def load_signals_glossary() -> dict[str, str]:
    """Load the `_signals_glossary` section from every config_docs/*.md.

    Returns {signal_name: markdown_description}. Used by the
    `WeightFamilyEditModal` to render a collapsible "信号术语速查"
    block — only entries whose name matches a leaf in the family being
    edited are shown, so crypto/magnitude shows `price_z_score` etc.
    but not `sustained_drift` (which only appears in political).

    Aggregating across all files is forward-compatible: if a future doc
    file (e.g. `mispricing.md`) adds its own `## _signals_glossary`,
    those entries fold in. Today only `movement.md` defines one.
    """
    glossary: dict[str, str] = {}
    for md_path in sorted(_DOCS_DIR.glob("*.md")):
        if md_path.name.startswith("_"):
            continue
        glossary.update(_parse_signals_glossary(md_path))
    return glossary
