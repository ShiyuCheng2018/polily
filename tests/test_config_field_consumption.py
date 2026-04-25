"""Meta-test: every alive PolilyConfig leaf must have a production consumer.

Catches regressions where a new config field is added but never wired up,
OR where a consumer is removed but the field stays around. Phase 0
established the alive-set; this test enforces it going forward.

Strategy: import the audit script's grep helper and assert that every
non-exempt leaf has at least one production reference. EXEMPTION_LIST is
for fields that are intentionally dormant (none expected after Phase 0).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make scripts/ importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

import audit_config_usage as audit  # noqa: E402

from polily.core.config import PolilyConfig


# Fields that are intentionally not consumed by production code.
# Each entry needs a comment explaining WHY it's exempt.
EXEMPTION_LIST: set[str] = set()

# Fields whose audit verdict comes from a LOW-SPECIFICITY grep match
# (level 3 `last_seg` or level 4 `quoted_key`). A human must verify
# each is a real consumer, not a false alive from a shared identifier
# name (e.g., `enabled`) or accidental string overlap (e.g., a leaf's
# last segment happening to appear as a dict key in unrelated code).
#
# Whis re-review (2026-04-25, Should-Fix 1) caught: all 26 leaves under
# `movement.weights.*` are alive only because their last segments
# (`price_z_score`, etc.) appear as dict keys in `_NORM_RANGES` in
# `monitor/scorer.py:14-25`. Their actual consumer is dict iteration
# at `scorer.py:43,50` (`for signal_name, weight in
# weights.magnitude.items()`), where the field name never appears as a
# literal in source. If `_NORM_RANGES` were renamed, the cascade would
# silently flip these to DEAD even though they're still consumed.
#
# Format: key_path → "verified consumer location" (file:line + brief explanation)
LOW_SPECIFICITY_VERIFIED: dict[str, str] = {
    # Pre-populated for the known dict-iteration consumer.
    # The 26 movement weights leaves all share the same anchor:
    # `polily/monitor/scorer.py:43,50` does `for signal_name, weight in weights.<family>.items()`,
    # iterating over the dict — field names are runtime variables, not
    # literals.
    **{
        f"movement.weights.{mt}.{family}.{signal}":
            "monitor/scorer.py:43,50 — dict iteration via weights.<family>.items()"
        for mt in ("crypto", "political", "economic_data", "default")
        for family in ("magnitude", "quality")
        # Signals here mirror the Pydantic defaults; if MovementWeights
        # adds new keys, this dict must be updated. The `test_no_unexplained_low_specificity_alives`
        # gate enforces no silent additions.
        for signal in (
            "price_z_score", "book_imbalance", "fair_value_divergence",
            "underlying_z_score", "cross_divergence",
            "volume_ratio", "trade_concentration",
            "volume_price_confirmation", "sustained_drift",
            "time_decay_adjusted_move",
        )
    },
    # NOTE: not all (mt, family, signal) tuples exist in PolilyConfig
    # defaults — e.g., `crypto.magnitude.sustained_drift` is not a
    # default key. The dict-comprehension over-includes; entries for
    # non-existent leaves are harmless (they only matter if the meta-test
    # encounters that leaf). The test will only check entries it
    # actually finds in the cascade.
}


def test_every_alive_config_leaf_has_production_consumer():
    """If this fails, you either:
    1. Added a config field but didn't wire it up (do the wiring), OR
    2. Removed code that consumed a field (delete the field too), OR
    3. Renamed/moved code such that grep no longer finds it (review and
       either update grep heuristic in scripts/audit_config_usage.py or
       add the field to EXEMPTION_LIST with a reason).
    """
    cfg = PolilyConfig()
    leaves = audit.enumerate_pydantic_leaves(cfg)

    dead_fields = []
    for leaf in leaves:
        if leaf in EXEMPTION_LIST:
            continue
        n, _samples = audit.grep_production_refs(leaf)
        if n == 0:
            dead_fields.append(leaf)

    assert not dead_fields, (
        f"{len(dead_fields)} config leaves have NO production consumer:\n"
        + "\n".join(f"  - {f}" for f in sorted(dead_fields))
        + "\n\nFix by: deleting the field, wiring it up, or adding to "
        "EXEMPTION_LIST with a reason."
    )


def test_no_unexplained_low_specificity_alives():
    """Every config leaf that is alive ONLY by LOW-specificity grep
    matching (level 3 `last_seg` or level 4 `quoted_key`) must be in
    `LOW_SPECIFICITY_VERIFIED` with a documented consumer location.

    Catches two false-alive classes Whis flagged:
    1. Last-segment shared identifiers (e.g., `enabled` shared by
       multiple sections; `crypto`/`political` shared by config keys +
       market type strings).
    2. Quoted-key accidental overlap (e.g., movement.weights leaves
       matching `_NORM_RANGES` dict literals in scorer.py despite
       actual consumption being dict iteration).

    Without this gate, the meta-test could pass while silently relying
    on noisy matches that disappear if the surrounding code is
    refactored.
    """
    cfg = PolilyConfig()
    leaves = audit.enumerate_pydantic_leaves(cfg)
    LOW_SPEC_LEVELS = {"last_seg", "quoted_key"}

    unexplained = []
    for leaf in leaves:
        if leaf in EXEMPTION_LIST:
            continue
        n, samples = audit.grep_production_refs(leaf)
        if n == 0 or not samples:
            continue
        match_level = samples[0].split("] ")[0].lstrip("[")
        if match_level in LOW_SPEC_LEVELS and leaf not in LOW_SPECIFICITY_VERIFIED:
            unexplained.append((leaf, match_level))

    assert not unexplained, (
        f"{len(unexplained)} alive-by-low-specificity leaves lack a "
        f"verified consumer entry in LOW_SPECIFICITY_VERIFIED:\n"
        + "\n".join(f"  - {leaf} [{level}]" for leaf, level in sorted(unexplained))
        + "\n\nFix by: locating the actual consumer in production code "
        "and adding it to LOW_SPECIFICITY_VERIFIED with file:line + "
        "explanation. Low-specificity matches (last_seg, quoted_key) "
        "are noise-prone and must be human-verified."
    )
