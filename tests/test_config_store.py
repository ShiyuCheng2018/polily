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


from polily.core.config import PolilyConfig
from polily.core.config_store import _flatten_pydantic


def test_flatten_pydantic_scalar_leaves():
    """Top-level scalars become dot-notation keys."""
    flat = _flatten_pydantic(PolilyConfig())
    assert flat["movement.magnitude_threshold"] == 70
    assert flat["movement.quality_threshold"] == 60
    assert flat["wallet.starting_balance"] == 100.0
    assert flat["api.request_timeout_seconds"] == 20


def test_flatten_pydantic_nested_dict_of_basemodel():
    """movement.weights[type] dict-of-MovementWeights flattens to leaves."""
    flat = _flatten_pydantic(PolilyConfig())
    # Per design §12.A.2 — 26 weights leaves
    assert flat["movement.weights.crypto.magnitude.price_z_score"] == 0.15
    assert flat["movement.weights.political.magnitude.sustained_drift"] == 0.40
    assert flat["movement.weights.default.quality.volume_ratio"] == 0.40


def test_flatten_pydantic_includes_ephemeral_fields():
    """_flatten_pydantic returns ALL leaves; EPHEMERAL filtering happens
    at seed/save/load layers, not at flatten."""
    flat = _flatten_pydantic(PolilyConfig())
    assert "api.user_agent" in flat


def test_flatten_pydantic_total_leaf_count_is_47():
    """Locks the 47-leaf invariant from design §3.2.

    If this fails the schema changed — update the design doc + this test
    together (and audit territory A whitelist before continuing).
    """
    flat = _flatten_pydantic(PolilyConfig())
    assert len(flat) == 47, f"expected 47 leaves, got {len(flat)}: {sorted(flat.keys())}"


from polily.core.config_store import _unflatten


def test_unflatten_scalar_leaves():
    flat = {
        "movement.magnitude_threshold": 50,
        "wallet.starting_balance": 200.0,
    }
    nested = _unflatten(flat)
    assert nested == {
        "movement": {"magnitude_threshold": 50},
        "wallet": {"starting_balance": 200.0},
    }


def test_unflatten_deeply_nested_weights():
    flat = {
        "movement.weights.crypto.magnitude.price_z_score": 0.15,
        "movement.weights.crypto.magnitude.book_imbalance": 0.10,
        "movement.weights.crypto.quality.volume_ratio": 0.40,
    }
    nested = _unflatten(flat)
    assert nested == {
        "movement": {
            "weights": {
                "crypto": {
                    "magnitude": {
                        "price_z_score": 0.15,
                        "book_imbalance": 0.10,
                    },
                    "quality": {"volume_ratio": 0.40},
                },
            },
        },
    }


def test_flatten_then_unflatten_roundtrips():
    """flatten → unflatten → model_validate must equal original PolilyConfig."""
    original = PolilyConfig()
    flat = _flatten_pydantic(original)
    nested = _unflatten(flat)
    rebuilt = PolilyConfig.model_validate(nested)
    assert rebuilt.model_dump() == original.model_dump()


import json
from polily.core.config_store import ensure_seeded


def test_ensure_seeded_populates_empty_db(polily_db):
    """First-run seed inserts 46 rows (47 leaves minus 1 EPHEMERAL)."""
    ensure_seeded(polily_db)

    cur = polily_db.conn.execute("SELECT COUNT(*) FROM config")
    count = cur.fetchone()[0]
    assert count == 46, f"expected 46 rows (47 - 1 ephemeral), got {count}"


def test_ensure_seeded_skips_ephemeral_fields(polily_db):
    """api.user_agent must NOT appear in db.config — it's runtime-computed."""
    ensure_seeded(polily_db)

    cur = polily_db.conn.execute(
        "SELECT key_path FROM config WHERE key_path = 'api.user_agent'"
    )
    assert cur.fetchone() is None, "api.user_agent should not be persisted"


def test_ensure_seeded_stores_values_as_json(polily_db):
    """Values are JSON-encoded so types round-trip cleanly."""
    ensure_seeded(polily_db)

    cur = polily_db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'movement.magnitude_threshold'"
    )
    raw = cur.fetchone()[0]
    assert json.loads(raw) == 70

    cur = polily_db.conn.execute(
        "SELECT value FROM config WHERE key_path = 'mispricing.enabled'"
    )
    assert json.loads(cur.fetchone()[0]) is True
