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
