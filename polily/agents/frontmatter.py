"""YAML frontmatter splitter for agent markdown output.

Splits a string of the form:

    ---
    key: value
    ---

    body...

into ({key: value, ...}, body_str). Defensive: if frontmatter is missing or
malformed, returns ({}, original_input) so the caller can still display the body.
"""
from __future__ import annotations

import yaml


def split_frontmatter(raw: str) -> tuple[dict, str]:
    """Split agent markdown output into (frontmatter_dict, body_str).

    Returns ({}, raw) when no frontmatter is detected or YAML parse fails.
    """
    if not raw.startswith("---\n") and not raw.startswith("---\r\n"):
        return {}, raw

    # Find the closing '---' fence
    body_start = raw.find("\n---\n", 4)
    if body_start == -1:
        body_start = raw.find("\n---\r\n", 4)
    if body_start == -1:
        # No closing fence; treat entire input as body
        return {}, raw

    fm_text = raw[4:body_start]
    body = raw[body_start + 5 :]  # past '\n---\n'

    try:
        fm = yaml.safe_load(fm_text)
        if not isinstance(fm, dict):
            return {}, raw
        return fm, body
    except yaml.YAMLError:
        return {}, raw
