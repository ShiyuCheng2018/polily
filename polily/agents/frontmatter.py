"""YAML frontmatter splitter for agent markdown output.

Splits a string of the form:

    ---
    key: value
    ---

    body...

into ({key: value, ...}, body_str). Defensive: if frontmatter is missing or
malformed, returns ({}, original_input) so the caller can still display the body.

v0.12.0 hotfix — preamble tolerance:
    Real-world agent outputs occasionally include a status preamble before
    the opening `---` (e.g., "数据已收集完毕，生成完整分析。" or
    "Here's the analysis:"). protocol.md forbids this, but if the agent
    slips one in we still want to extract the frontmatter rather than
    silently dropping all 4 fields. The preamble itself is treated as
    noise and dropped from the body — agents must put real content
    inside the markdown body, not before the YAML block.
"""
from __future__ import annotations

import yaml

# Bound the search for the opening `---` fence. If we haven't found it
# within this many lines, assume there's no frontmatter at all (avoids
# misinterpreting a horizontal rule deep in a body-only document as the
# start of a YAML block).
_MAX_PREAMBLE_LINES = 50


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """Split agent markdown output into (frontmatter_dict, body_str).

    Tolerates up to _MAX_PREAMBLE_LINES of leading content (preamble or
    blank lines) before the opening `---`. Returns ({}, raw) when no
    valid YAML mapping is found between two `---` fences.
    """
    lines = raw.splitlines(keepends=True)

    # Find the opening fence: a line that, stripped of trailing newline,
    # is exactly "---". Bounded search avoids misinterpreting a
    # horizontal rule deep in a body-only document.
    open_idx = None
    for i, line in enumerate(lines[:_MAX_PREAMBLE_LINES]):
        if line.rstrip("\r\n") == "---":
            open_idx = i
            break
    if open_idx is None:
        return {}, raw

    # Find the closing fence after the opener.
    close_idx = None
    for j in range(open_idx + 1, len(lines)):
        if lines[j].rstrip("\r\n") == "---":
            close_idx = j
            break
    if close_idx is None:
        return {}, raw

    fm_text = "".join(lines[open_idx + 1 : close_idx])
    body = "".join(lines[close_idx + 1 :])

    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return {}, raw

    # Reject non-mapping YAML (e.g., a string scalar from prose between
    # two horizontal rules) — never fabricate fields.
    if not isinstance(fm, dict):
        return {}, raw

    return fm, body
