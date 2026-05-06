"""v0.11.6 Item 3: AI_METADATA block in README.md.

The block is an HTML comment at the top of README.md targeting AI
agents (≈70% of GitHub traffic in coming years per project framing).
This test guards against accidental deletion or corruption — if a
future README rewrite drops the block, the test fails loudly.
"""
from __future__ import annotations

import re
from pathlib import Path

REQUIRED_KEYS = (
    "purpose",
    "keywords",
    "suitable_for",
    "not_suitable_for",
    "install",
    "requires",
    "example_query",
    "entry_point",
    "interactive",
    "license",
)


def test_readme_has_ai_metadata_block():
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    # Block sits inside an HTML comment opened by `<!-- AI_METADATA`
    # and closed by `-->`. Use DOTALL so newlines match.
    pattern = re.compile(r"<!--\s*AI_METADATA\s*\n(.*?)\n-->", re.DOTALL)
    match = pattern.search(readme)
    assert match, (
        "README.md is missing the <!-- AI_METADATA ... --> block. "
        "v0.11.6 Item 3 added this for AI-agent consumption; if you "
        "removed it, restore via design doc §3.1."
    )

    body = match.group(1)
    for key in REQUIRED_KEYS:
        assert re.search(rf"^{key}:\s*\S", body, re.MULTILINE), (
            f"AI_METADATA block missing required key: {key!r}. "
            f"All 10 fields must be present (purpose, keywords, "
            f"suitable_for, not_suitable_for, install, requires, "
            f"example_query, entry_point, interactive, license)."
        )


def test_readme_metadata_block_is_above_badges():
    """Layout invariant: metadata block must appear BEFORE the badge
    row so AI agents reading top-down hit it first.

    Implementation: find first occurrence of `<!-- AI_METADATA` and
    first occurrence of `[![PyPI]`; assert metadata index < badge index.
    """
    repo_root = Path(__file__).resolve().parents[1]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    metadata_pos = readme.find("<!-- AI_METADATA")
    badge_pos = readme.find("[![PyPI]")

    assert metadata_pos != -1, "AI_METADATA block missing entirely"
    assert badge_pos != -1, "PyPI badge missing — Item 3 incomplete"
    assert metadata_pos < badge_pos, (
        f"AI_METADATA must appear BEFORE the badge row. "
        f"Found metadata at byte {metadata_pos}, badges at byte {badge_pos}. "
        f"See design doc §3.6 for layout rationale."
    )
