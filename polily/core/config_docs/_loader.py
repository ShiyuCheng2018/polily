"""Parse config_docs/*.md → dict[key_path, html_description]."""
from __future__ import annotations

import re
from pathlib import Path

# Section header that mints a new key block: `## <key_path>` where key_path
# starts with a letter (so `## _signals_glossary` is skipped).
_SECTION_RE = re.compile(r"^##\s+(?P<key>[a-zA-Z][\w.]*)\s*$")

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
