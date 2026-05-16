"""Unit tests for SF10 — TERRITORY_A is a closed allowlist, not a prefix match.

Pre-SF10, ``is_territory_a`` did
``any(key.startswith(p) for p in TERRITORY_A_PREFIXES)``. That meant ANY
future leaf added under ``wallet.`` / ``movement.`` / ``mispricing.`` /
``scoring.thresholds.`` would auto-become editable in the TUI Edit modal —
including hypothetical ``wallet.api_key`` (someday) which would silently
appear as a free-text input and risk the user editing / leaking it.

Post-SF10, TERRITORY_A is computed once from
``_flatten_pydantic(PolilyConfig())`` minus EPHEMERAL_FIELDS minus a new
HIDDEN_IN_TUI set — so adding any new leaf is HIDDEN by default. Promotion
to territory A is an explicit code change, not an accident.
"""
from __future__ import annotations

from polily.core.config import PolilyConfig
from polily.core.config_store import (
    EPHEMERAL_FIELDS,
    HIDDEN_IN_TUI,
    TERRITORY_A,
    _flatten_pydantic,
    is_territory_a,
)


def test_territory_a_is_frozenset_of_exact_count():
    """41 leaves total (v0.12.0: added active_strategy — 40 → 41).
    If this fails the schema changed — update HIDDEN_IN_TUI /
    EPHEMERAL_FIELDS or accept the new territory A member explicitly.
    """
    assert isinstance(TERRITORY_A, frozenset)
    assert len(TERRITORY_A) == 41, (
        f"expected 41 territory A keys, got {len(TERRITORY_A)}: "
        f"{sorted(TERRITORY_A)}"
    )


def test_territory_a_partition_covers_all_leaves():
    """Every leaf in PolilyConfig is in exactly one of:
    TERRITORY_A / HIDDEN_IN_TUI / EPHEMERAL_FIELDS. No leaks, no
    duplicates."""
    all_keys = frozenset(_flatten_pydantic(PolilyConfig()).keys())
    union = TERRITORY_A | HIDDEN_IN_TUI | EPHEMERAL_FIELDS
    assert union == all_keys, (
        f"partition mismatch:\n"
        f"  unaccounted: {sorted(all_keys - union)}\n"
        f"  fictional:   {sorted(union - all_keys)}"
    )
    # Ensure mutual exclusion — no key in two sets.
    assert not (TERRITORY_A & HIDDEN_IN_TUI)
    assert not (TERRITORY_A & EPHEMERAL_FIELDS)
    assert not (HIDDEN_IN_TUI & EPHEMERAL_FIELDS)


def test_hidden_in_tui_exact_membership():
    """Lock the 8 currently-hidden leaves. Future additions to
    HIDDEN_IN_TUI must update this test in the same commit (forces a
    conscious choice, mirrors EPHEMERAL_FIELDS pattern).

    v0.11.4: added update_check.last_dismissed_version — TUI-managed
    state for the "new version available" indicator, not user-tunable.
    feat/runtime-i18n: added tui.language — runtime-mutable via F2;
    canonical value lives in user_prefs, PolilyConfig field is just a
    startup fallback default.
    """
    assert frozenset({
        "api.request_timeout_seconds",
        "ai.narrative_writer.model",
        "ai.narrative_writer.timeout_seconds",
        "ai.narrative_writer.max_prompt_chars",
        "tui.heartbeat_seconds",
        "tui.language",
        "archiving.db_file",
        "update_check.last_dismissed_version",
    }) == HIDDEN_IN_TUI


def test_is_territory_a_rejects_hypothetical_wallet_api_key():
    """The future-hypothetical case the SF10 design protects against.

    Today no such leaf exists in PolilyConfig — but the prefix match
    (`wallet.*`) would auto-allow it as soon as someone added it. Pin
    that the new allowlist gate refuses it instead.
    """
    assert is_territory_a("wallet.api_key") is False


def test_is_territory_a_excludes_ephemeral():
    assert is_territory_a("api.user_agent") is False


def test_is_territory_a_excludes_hidden():
    assert is_territory_a("archiving.db_file") is False
    assert is_territory_a("tui.heartbeat_seconds") is False
    assert is_territory_a("ai.narrative_writer.model") is False


def test_is_territory_a_recognizes_real_movement_key():
    """Sanity — real territory A leaves still resolve True."""
    assert is_territory_a("movement.magnitude_threshold") is True
    assert is_territory_a("movement.weights.crypto.magnitude.price_z_score") is True
    assert is_territory_a("scoring.thresholds.tier_a_min_score") is True
    assert is_territory_a("mispricing.enabled") is True
    assert is_territory_a("wallet.starting_balance") is True


def test_is_territory_a_rejects_unknown_key():
    """A key_path that isn't in PolilyConfig at all returns False —
    the allowlist doesn't accidentally include it via prefix match."""
    assert is_territory_a("movement.does_not_exist") is False
    assert is_territory_a("wallet.does_not_exist") is False
