"""Audit which PolilyConfig leaves are actually consumed in production code.

Phase 0 helper — run once per audit pass. Output is a markdown table that
serves as input for the dead-config deletion tasks.

Usage:
    python scripts/audit_config_usage.py > docs/internal/plans/2026-04-25-config-audit-results.md
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from pydantic import BaseModel


REPO_ROOT = Path(__file__).resolve().parent.parent
PRODUCTION_GLOB_DIRS = ["polily"]
EXCLUDED_FILES = {"polily/core/config.py"}


def enumerate_pydantic_leaves(model: BaseModel, prefix: str = "") -> list[str]:
    """Walk a Pydantic model and return all leaf paths in dot notation.

    Leaves include: scalars (int/float/str/bool), lists, and dict values
    (treated as leaves at one level deep — `dict[str, X]` becomes
    `prefix.<key>` per dict key).
    """
    leaves: list[str] = []
    for field_name, _field_info in type(model).model_fields.items():
        value = getattr(model, field_name)
        path = f"{prefix}.{field_name}" if prefix else field_name
        if isinstance(value, BaseModel):
            leaves.extend(enumerate_pydantic_leaves(value, path))
        elif isinstance(value, dict):
            for key, sub_value in value.items():
                sub_path = f"{path}.{key}"
                if isinstance(sub_value, BaseModel):
                    leaves.extend(enumerate_pydantic_leaves(sub_value, sub_path))
                else:
                    leaves.append(sub_path)
        else:
            leaves.append(path)
    return leaves


def grep_production_refs(key_path: str) -> tuple[int, list[str]]:
    """Count grep matches for `key_path` in production code, returning
    (match_count, sample_lines).

    Strategy: try multiple patterns ordered from most-specific to least.
    Stop at the first pattern that yields matches; if all yield zero,
    return 0. This avoids false-alives from last-segment collisions
    (e.g., `enabled` is shared by 4+ different config sections).

    Patterns tried, in order:
      1. Full dotted suffix: `\\.movement\\.weights\\.crypto\\.magnitude\\.price_z_score\\b`
      2. Two-segment suffix: `\\.crypto\\.magnitude\\.price_z_score\\b` (handles `weights = config.weights.get(...).magnitude`)
      3. One-segment suffix: `\\.price_z_score\\b` (last resort; will produce false alives — flagged in output)
      4. Quoted dict-key: `"price_z_score"` or `'price_z_score'` (only when key segment looks like a string identifier, not a number)

    Returns (count, sample_lines). Caller MUST inspect samples for
    last-segment-only matches (level 3) since those are noisy.

    Whis review caught: last-segment-only matching collapses
    `MovementConfig.enabled`, `ArchivingConfig.enabled`, `AgentConfig.enabled`,
    `MultiOutcomeConfig.enabled` into the same regex hit, producing false
    alives. The cascade above tries to disambiguate before falling back.
    """
    segments = key_path.split(".")
    patterns_to_try: list[tuple[str, str]] = []

    # Level 1: full path
    full_path_re = r"\." + r"\.".join(re.escape(s) for s in segments) + r"\b"
    patterns_to_try.append(("full_path", full_path_re))

    # Level 2: trailing-2 segments (helpful for `cfg.scoring.thresholds.tier_a_min_score`
    # where `scoring` may be unbound to a local var like `s = config.scoring`)
    if len(segments) >= 2:
        two_seg_re = r"\." + r"\.".join(re.escape(s) for s in segments[-2:]) + r"\b"
        patterns_to_try.append(("two_seg", two_seg_re))

    # Level 3: last segment ONLY (noisy, last resort)
    last_segment = segments[-1]
    last_seg_re = rf"\.{re.escape(last_segment)}\b"
    patterns_to_try.append(("last_seg", last_seg_re))

    # Level 4: quoted (for dict-key access like config.weights["price_z_score"])
    # Only if last segment is a valid Python identifier (excludes things like "5")
    if last_segment.isidentifier():
        quoted_re = rf'"{re.escape(last_segment)}"|\'{re.escape(last_segment)}\''
        patterns_to_try.append(("quoted_key", quoted_re))

    for level_name, pattern in patterns_to_try:
        cmd = [
            "grep", "-rnE", pattern,
            "--include=*.py",
            *[str(REPO_ROOT / d) for d in PRODUCTION_GLOB_DIRS],
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        lines = [
            ln for ln in result.stdout.splitlines()
            if not any(excl in ln for excl in EXCLUDED_FILES)
        ]
        if lines:
            # Return at the first non-empty pattern level; tag samples with level
            tagged = [f"[{level_name}] {ln}" for ln in lines[:5]]
            return len(lines), tagged

    return 0, []


def main() -> None:
    from polily.core.config import PolilyConfig

    cfg = PolilyConfig()
    leaves = enumerate_pydantic_leaves(cfg)

    print("# Polily Config Audit Results")
    print()
    print(f"Generated: {subprocess.check_output(['date', '-u', '+%Y-%m-%dT%H:%M:%SZ']).decode().strip()}")
    print(f"Total leaves: {len(leaves)}")
    print()
    print("| key_path | refs | match level | verdict | sample |")
    print("|---|---|---|---|---|")

    last_seg_alives: list[str] = []  # for human review

    for leaf in sorted(leaves):
        n, samples = grep_production_refs(leaf)
        verdict = "alive" if n > 0 else "DEAD"
        # Detect noisy last_seg matches; flag for manual review
        match_level = samples[0].split("] ")[0].lstrip("[") if samples else "—"
        sample_summary = (samples[0][:80] + "…") if samples else ""
        if match_level == "last_seg":
            last_seg_alives.append(leaf)
        print(f"| `{leaf}` | {n} | {match_level} | {verdict} | `{sample_summary}` |")

    # Render a "needs human review" tail if any last_seg-only alives were found
    if last_seg_alives:
        print()
        print("## ⚠ Needs human review (last-segment-only matches)")
        print()
        print("These are ALIVE only by virtue of last-segment grep matching, which is")
        print("the noisiest level. A human reviewer must confirm whether each is a")
        print("genuine consumer or a false alive. If any are false alives, the audit")
        print("verdict for that key flips to DEAD.")
        print()
        for leaf in last_seg_alives:
            print(f"- `{leaf}`")


if __name__ == "__main__":
    main()
