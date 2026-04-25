"""Tests for scripts/audit_config_usage.py — the Phase 0 audit tool.

The audit tool is a one-shot utility but we test it because its output
drives wholesale code deletion. Bugs in enumeration or grep would either
miss dead fields (we keep cruft) or flag alive fields (we delete real
behavior). Both are bad enough to warrant test coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make scripts/ importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

import audit_config_usage as audit  # noqa: E402


def test_enumerate_pydantic_leaves_returns_dot_paths():
    from polily.core.config import PolilyConfig
    leaves = audit.enumerate_pydantic_leaves(PolilyConfig())
    # Some sample leaves we know exist (from current config.py)
    assert "movement.magnitude_threshold" in leaves
    assert "wallet.starting_balance" in leaves
    assert "ai.narrative_writer.model" in leaves
    # No mid-paths
    assert "movement" not in leaves
    assert "wallet" not in leaves


def test_enumerate_handles_dict_fields_as_leaves():
    """movement.weights is a dict; should expand into per-key paths."""
    from polily.core.config import PolilyConfig
    leaves = audit.enumerate_pydantic_leaves(PolilyConfig())
    assert any(k.startswith("movement.weights.crypto.magnitude.") for k in leaves)


def test_grep_production_refs_returns_tuple():
    """Helper returns (count, sample_lines)."""
    n, samples = audit.grep_production_refs("wallet.starting_balance")
    assert isinstance(n, int)
    assert isinstance(samples, list)
    assert n > 0  # confirmed alive — heavily used


def test_grep_production_refs_disambiguates_shared_last_segment():
    """`enabled` is shared by multiple config sections — the cascade
    heuristic must NOT collapse them at high specificity.

    Test scenario: at audit time, both `MovementConfig.enabled` (about
    to be deleted in Task 5) and `MispricingConfig.enabled` (alive,
    consumed at `mispricing.py:121` as `config.enabled`) exist. The
    cascade should distinguish them:
      - `grep_production_refs("movement.enabled")` should return 0 at
        full_path (`\\.movement\\.enabled\\b`) and two_seg
        (`\\.enabled\\b` after `\\.movement\\.`); only at last_seg
        could it potentially confuse with `mispricing.enabled`.
      - If the cascade falls through to last_seg and finds the
        mispricing match, the heuristic flags this as low-specificity —
        a human reviewer (or the `LOW_SPECIFICITY_VERIFIED` registry)
        must confirm vs reject.
    """
    n, samples = audit.grep_production_refs("movement.enabled")
    # At this point in Phase 0 timeline (Task 2 — before Task 5 deletes
    # MovementConfig.enabled), the field still exists in PolilyConfig
    # but has no production consumer. Ideal cascade behavior:
    #   - Levels 1-2 (full_path, two_seg): 0 matches (correct)
    #   - Level 3 (last_seg): may match mispricing's `.enabled` → tagged "[last_seg]"
    # Test enforces: high-specificity levels do NOT spuriously match.
    if n > 0:
        levels = [s.split("] ")[0].lstrip("[") for s in samples]
        assert "full_path" not in levels and "two_seg" not in levels, (
            f"movement.enabled should not match at full_path or two_seg "
            f"levels (no `.movement.enabled` literal in production code); "
            f"got samples: {samples}"
        )
