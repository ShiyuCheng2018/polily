"""Unit tests for polily.core.config_store."""
from __future__ import annotations

from polily.core.config_store import EPHEMERAL_FIELDS


def test_ephemeral_fields_contains_user_agent():
    """api.user_agent is the only known EPHEMERAL field (per Q3 / design §3.2)."""
    assert "api.user_agent" in EPHEMERAL_FIELDS


def test_ephemeral_fields_is_frozenset():
    """frozenset enforces immutability — can't be mutated at runtime."""
    assert isinstance(EPHEMERAL_FIELDS, frozenset)


from polily.core.config_store import (
    TERRITORY_A_PREFIXES,
    is_territory_a,
)


def test_territory_a_prefixes_covers_4_user_facing_sections():
    """Per Q1 — only 4 sections are TUI-editable."""
    assert TERRITORY_A_PREFIXES == (
        "movement.",
        "scoring.thresholds.",
        "mispricing.",
        "wallet.",
    )


def test_is_territory_a_recognizes_movement_keys():
    assert is_territory_a("movement.magnitude_threshold") is True
    assert is_territory_a("movement.weights.crypto.magnitude.price_z_score") is True


def test_is_territory_a_excludes_hidden_sections():
    """api.* / tui.* / ai.* / archiving.* are HIDDEN_IN_TUI per Q1."""
    assert is_territory_a("api.request_timeout_seconds") is False
    assert is_territory_a("tui.heartbeat_seconds") is False
    assert is_territory_a("ai.narrative_writer.model") is False
    assert is_territory_a("archiving.db_file") is False


def test_is_territory_a_excludes_ephemeral_fields():
    """api.user_agent is EPHEMERAL — never editable via TUI."""
    assert is_territory_a("api.user_agent") is False


def test_territory_a_prefixes_top_levels_align_with_pydantic_schema():
    """Schema drift guard — if PolilyConfig adds a top-level section,
    either add it to TERRITORY_A_PREFIXES (visible) or to
    _HIDDEN_TOP_LEVELS (intentionally hidden). Forces conscious choice."""
    from polily.core.config import PolilyConfig
    pydantic_top = set(PolilyConfig.model_fields.keys())
    territory_top = {p.split(".")[0] for p in TERRITORY_A_PREFIXES}
    hidden_top = {"api", "tui", "ai", "archiving"}
    assert territory_top | hidden_top == pydantic_top, (
        f"PolilyConfig schema drift: section appeared/disappeared.\n"
        f"  pydantic top-level: {sorted(pydantic_top)}\n"
        f"  territory_a:        {sorted(territory_top)}\n"
        f"  hidden:             {sorted(hidden_top)}\n"
        f"  unaccounted:        {sorted(pydantic_top - territory_top - hidden_top)}"
    )
