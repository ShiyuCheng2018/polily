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

    Test scenario: at audit time, `MispricingConfig.enabled` is consumed
    via `config.enabled` in mispricing.py:121. `MovementConfig.enabled`
    is dead (no production consumer). The cascade for
    `grep_production_refs("movement.enabled")` should:
      - Level 1 (full_path `\\.movement\\.enabled\\b`): 0 matches
      - Level 2 (two_seg `\\.movement\\.enabled\\b`): same as level 1, 0 matches
      - Level 3 (last_seg `\\.enabled\\b`): falls through, matches mispricing
      - Result: tagged "[last_seg]" — flagged for human review
    """
    n, samples = audit.grep_production_refs("movement.enabled")
    # Cascade MUST find at least one match (mispricing.enabled at last_seg)
    assert n > 0, (
        f"Expected fall-through to last_seg matching `mispricing.enabled` "
        f"in mispricing.py; got n=0. Cascade may be broken."
    )
    levels = [s.split("] ")[0].lstrip("[") for s in samples]
    # Must NOT match at full_path or two_seg (would mean false-positive
    # disambiguation failure)
    assert "full_path" not in levels, (
        f"movement.enabled spuriously matched at full_path: {samples}"
    )
    assert "two_seg" not in levels, (
        f"movement.enabled spuriously matched at two_seg: {samples}"
    )
    # SHOULD match at last_seg (the documented fall-through behavior)
    assert "last_seg" in levels, (
        f"Expected last_seg fall-through; actual levels: {levels}"
    )


def test_enumerate_handles_empty_dict_with_basemodel_value():
    """Empty-default dict fields with BaseModel value type must surface
    in the leaf list (via <empty> placeholder), otherwise dead-config
    audits would silently miss them.

    Reproduces the original bug where empty-default `dict[str, BaseModel]`
    fields produced zero leaves and were invisible to the audit.
    """
    from pydantic import BaseModel

    class _SubField(BaseModel):
        threshold: int = 100
        label: str = "x"

    class _Container(BaseModel):
        empty_typed_dict: dict[str, _SubField] = {}
        regular_field: int = 42

    leaves = audit.enumerate_pydantic_leaves(_Container())
    # The empty dict's value-type leaves must be exposed
    assert any("empty_typed_dict.<empty>.threshold" in lf for lf in leaves), (
        f"Empty typed dict not surfaced; leaves: {leaves}"
    )
    assert any("empty_typed_dict.<empty>.label" in lf for lf in leaves), (
        f"Empty typed dict label not surfaced; leaves: {leaves}"
    )
    # Regular fields still work
    assert "regular_field" in leaves
