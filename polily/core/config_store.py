"""DB-canonical config storage.

Per design §3.2 — db.config is the single source of truth for polily
configuration. Three field tiers:

- territory A (40 leaves): TUI-editable, persisted in db
- HIDDEN_IN_TUI (6 leaves): persisted in db but not exposed via TUI Edit modal
- EPHEMERAL_FIELDS (1 leaf): never persisted; computed at runtime via Pydantic
  default_factory (e.g., api.user_agent which follows __version__)

Public API:
    ensure_seeded(db)           — INSERT OR IGNORE all 47 leaves except EPHEMERAL
    load_all(db) -> dict        — read all rows, returns {key_path: value}
    upsert(db, key, value)      — write/overwrite a single key (TUI Edit modal)
    reset(db, key)              — write Pydantic default for key (modal Reset)

The "ephemeral" tier is enforced at three sites — seed skips them, save_knob
rejects them, load filters them out (defense-in-depth even if user does raw SQL).
"""
from __future__ import annotations


# Per design §3.2 — fields whose value is computed at runtime via Pydantic
# default_factory. They never go to db; PolilyConfig recomputes them on every
# instantiation. Adding a second EPHEMERAL field is rare; YAGNI on a more
# generic mechanism per §10.2.
EPHEMERAL_FIELDS: frozenset[str] = frozenset({
    "api.user_agent",  # Field(default_factory=_default_user_agent) → polily/<__version__>
})


# Per Q1 + Whis SF4 — territory A whitelist single source of truth.
# Tests (test_config_docs_coverage), production (ConfigView, ConfigEditModal)
# all import from here so they can't drift independently.
TERRITORY_A_PREFIXES: tuple[str, ...] = (
    "movement.",
    "scoring.thresholds.",
    "mispricing.",
    "wallet.",
)


def is_territory_a(key_path: str) -> bool:
    """True if key_path is TUI-editable (not HIDDEN_IN_TUI, not EPHEMERAL)."""
    if key_path in EPHEMERAL_FIELDS:
        return False
    return any(key_path.startswith(p) for p in TERRITORY_A_PREFIXES)


from typing import Any

from pydantic import BaseModel


def _flatten_pydantic(model: BaseModel, prefix: str = "") -> dict[str, Any]:
    """Walk a Pydantic model and return all leaf paths in dot notation.

    Mirrors the approach of `scripts/audit_config_usage.py::enumerate_pydantic_leaves`
    but returns the leaf VALUES (not just paths). Used by ensure_seeded
    to populate db.config with current Pydantic defaults.

    Handles:
      - scalar leaves (int / float / str / bool) → 1 entry per leaf
      - nested BaseModel → recurses with extended prefix
      - dict[str, BaseModel] (e.g., movement.weights) → recurses per dict key
      - dict[str, scalar] (e.g., MovementWeights.magnitude) → 1 entry per dict key

    Includes EPHEMERAL fields — filtering happens at the seed/save/load
    boundary, not here.
    """
    flat: dict[str, Any] = {}
    for field_name, _field_info in type(model).model_fields.items():
        value = getattr(model, field_name)
        path = f"{prefix}.{field_name}" if prefix else field_name
        if isinstance(value, BaseModel):
            flat.update(_flatten_pydantic(value, path))
        elif isinstance(value, dict):
            for key, sub_value in value.items():
                sub_path = f"{path}.{key}"
                if isinstance(sub_value, BaseModel):
                    flat.update(_flatten_pydantic(sub_value, sub_path))
                elif isinstance(sub_value, dict):
                    # Nested scalar dict (e.g., MovementWeights.magnitude is
                    # dict[str, float]). Each key is a final leaf.
                    for sub_key, leaf_value in sub_value.items():
                        flat[f"{sub_path}.{sub_key}"] = leaf_value
                else:
                    flat[sub_path] = sub_value
        else:
            flat[path] = value
    return flat


def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """Inverse of _flatten_pydantic — convert dot-notation dict to nested.

    Used by load_all to reconstruct kwargs for `PolilyConfig.model_validate`.
    """
    nested: dict[str, Any] = {}
    for key_path, value in flat.items():
        parts = key_path.split(".")
        cursor = nested
        for part in parts[:-1]:
            if part not in cursor:
                cursor[part] = {}
            elif not isinstance(cursor[part], dict):
                # Should not happen if _flatten_pydantic was the source —
                # would mean a key_path is both a scalar leaf and a parent.
                raise ValueError(
                    f"_unflatten conflict: {key_path} parent {part!r} "
                    f"already has scalar value {cursor[part]!r}"
                )
            cursor = cursor[part]
        cursor[parts[-1]] = value
    return nested


import json
from datetime import UTC, datetime

from polily.core.config import PolilyConfig


def ensure_seeded(db) -> None:
    """Idempotent seed — fills any missing leaf with its current Pydantic default.

    Per design §3.3:
      - Skips EPHEMERAL_FIELDS (api.user_agent etc. — computed at runtime)
      - Uses INSERT OR IGNORE so concurrent first-run callers (TUI + daemon)
        don't collide on the PRIMARY KEY constraint
      - Auto-restores user-deleted rows on next startup ("缺什么补什么")
      - Auto-adds new leaves when polily schema evolves in a future version

    Called by load_config() at every polily startup; idempotent and cheap.
    """
    defaults_flat = _flatten_pydantic(PolilyConfig())
    now = datetime.now(UTC).isoformat()
    rows = [
        (key, json.dumps(value), now)
        for key, value in defaults_flat.items()
        if key not in EPHEMERAL_FIELDS
    ]
    with db.conn:
        db.conn.executemany(
            "INSERT OR IGNORE INTO config (key_path, value, updated_at) VALUES (?, ?, ?)",
            rows,
        )
