"""DB-canonical config storage.

Per design §3.2 — db.config is the single source of truth for polily
configuration. Three field tiers:

- territory A (40 leaves): TUI-editable, persisted in db
- HIDDEN_IN_TUI (6 leaves): persisted in db but not exposed via TUI Edit modal
- EPHEMERAL_FIELDS (1 leaf): never persisted; computed at runtime via Pydantic
  default_factory (e.g., api.user_agent which follows __version__)

Public API (all implemented as of Phase 1):
    ensure_seeded(db)           — INSERT OR IGNORE all 47 leaves except EPHEMERAL
    load_all(db) -> dict        — read all rows, returns {key_path: value}
    upsert(db, key, value)      — write/overwrite a single key (TUI Edit modal)
    reset(db, key)              — write Pydantic default for key (modal Reset)

Internal:
    _migrate_yaml_to_db(db)     — one-shot v0.9.x → v0.10.0 legacy yaml import

The "ephemeral" tier is enforced at three sites — seed skips them, save_knob
rejects them, load filters them out (defense-in-depth even if user does raw SQL).
"""
from __future__ import annotations

import json
import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from polily.core.config import PolilyConfig

_log = logging.getLogger(__name__)


# SF1 (v0.10.0) — last migration status from this process. Read by
# `polily.cli._emit_migration_status_to_stderr` so CLI bootstrap can
# surface yaml→db migration outcomes (or .bak rescue) to the user.
# Process-local memory; cross-process is fine because every polily
# process either runs migration once on first config load or sees the
# 'skipped_already_migrated' sentinel and we want each process to
# announce its own migration result. Thread-safe via lock — load_config
# is only called from main thread in practice but ensure_seeded/migrate
# are also exposed.
MigrationStatus = (
    tuple[str, int]    # ("ok", n_keys_migrated)
    | tuple[str, str]  # ("skipped_invalid", reason)
    | tuple[str]       # ("skipped_no_yaml",) | ("skipped_already_migrated",)
)
_last_migration_status: MigrationStatus | None = None
_status_lock = threading.Lock()


def get_last_migration_status() -> MigrationStatus | None:
    """Return the most recent _migrate_yaml_to_db result, or None if not yet run.

    Used by polily.cli._emit_migration_status_to_stderr to localize and
    surface AC2-required upgrade feedback after CLI bootstrap loads config.
    """
    with _status_lock:
        return _last_migration_status


def _set_last_migration_status(status: MigrationStatus) -> None:
    global _last_migration_status
    with _status_lock:
        _last_migration_status = status


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
    """True if key_path is TUI-editable (not HIDDEN_IN_TUI, not EPHEMERAL).

    EPHEMERAL_FIELDS check happens BEFORE the prefix match, so even a
    key like 'movement.user_agent' (hypothetical) would be rejected if
    it lived in EPHEMERAL_FIELDS. This precedence matters for
    defense-in-depth: territory-A whitelist alone isn't sufficient if
    a future EPHEMERAL field happens to share a prefix with a real one.
    """
    if key_path in EPHEMERAL_FIELDS:
        return False
    return any(key_path.startswith(p) for p in TERRITORY_A_PREFIXES)


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

    Does not handle:
      - None-valued fields (would be stored as JSON null; PolilyConfig
        currently has no Optional models so untested)
      - list-typed fields (would be stored as Python list object; T1.5 +
        T1.7 JSON-serialize via dumps/loads. PolilyConfig currently has
        no list leaves in territory A; add an isinstance(value, list)
        branch if/when that changes)
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
                        _assert_supported_scalar(
                            f"{sub_path}.{sub_key}", leaf_value,
                        )
                        flat[f"{sub_path}.{sub_key}"] = leaf_value
                else:
                    _assert_supported_scalar(sub_path, sub_value)
                    flat[sub_path] = sub_value
        else:
            _assert_supported_scalar(path, value)
            flat[path] = value
    return flat


def _assert_supported_scalar(path: str, value: Any) -> None:
    """Reject sequence-typed and None-valued leaves with a clear error.

    SF9 (v0.10.0) — _flatten_pydantic / _unflatten / TUI Edit modal all
    assume scalar leaves. If a future schema-edit slips a list-typed or
    Optional-None-valued field in, every consumer would silently fall
    out of sync (db round-trips the JSON, model_validate accepts it, but
    _resolve_field_annotation + _coerce_value can't render or coerce
    the value in the Edit modal). Fail loud here so the regression
    surfaces at the seed/migrate boundary instead of as a half-broken
    UI later.
    """
    if isinstance(value, (list, tuple, set)):
        raise NotImplementedError(
            f"_flatten_pydantic doesn't support sequence-typed leaves yet "
            f"(got {type(value).__name__} at '{path}'). "
            f"Add explicit handling here + matching un-flatten + TUI editor support."
        )
    if value is None:
        raise NotImplementedError(
            f"_flatten_pydantic doesn't support None-valued leaves "
            f"(at '{path}'). Use a non-Optional field with a sensible default, "
            f"or extend this helper."
        )


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


def ensure_seeded(db) -> None:
    """Idempotent seed — fills any missing leaf with its current Pydantic default.

    Per design §3.3:
      - Skips EPHEMERAL_FIELDS (api.user_agent etc. — computed at runtime)
      - Uses INSERT OR IGNORE so concurrent first-run callers (TUI + daemon)
        don't collide on the PRIMARY KEY constraint
      - Auto-restores user-deleted rows on next startup ("缺什么补什么")
      - Auto-adds new leaves when polily schema evolves in a future version

    Called by load_config_from_db() at every polily startup; idempotent and cheap.
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


def load_all(db) -> dict[str, Any]:
    """Read all rows from db.config, return {key_path: deserialized_value}.

    Per design §4.2 — defensive filter excludes EPHEMERAL_FIELDS even if a
    row exists (someone might have done raw SQL). The Pydantic
    default_factory is the canonical source for those values.
    """
    cur = db.conn.execute("SELECT key_path, value FROM config")
    flat: dict[str, Any] = {}
    for key_path, raw_value in cur.fetchall():
        if key_path in EPHEMERAL_FIELDS:
            continue
        flat[key_path] = json.loads(raw_value)
    return flat


class ConfigSaveError(Exception):
    """Raised when a config save violates an invariant (EPHEMERAL field, etc.)."""


def upsert(db, key_path: str, value: Any) -> None:
    """Insert or update a single config row.

    Per design §4.2:
      - Rejects EPHEMERAL_FIELDS (those are runtime-computed, must never persist)
      - Refreshes updated_at on every write
      - Caller is responsible for Pydantic validation BEFORE calling this
        (see polily/core/config.py::save_knob)

    Used by:
      - TUI Edit modal save handler
      - polily config reset CLI escape hatch
    """
    if key_path in EPHEMERAL_FIELDS:
        raise ConfigSaveError(
            f"{key_path} is computed at runtime and cannot be persisted"
        )
    now = datetime.now(UTC).isoformat()
    with db.conn:
        db.conn.execute(
            """
            INSERT INTO config (key_path, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key_path) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key_path, json.dumps(value), now),
        )


def reset(db, key_path: str) -> None:
    """Reset a single key to its Pydantic default value.

    Per design §4.2 — writes the default back into db (does NOT delete
    the row), so yaml regen still exports a complete snapshot.

    Raises:
      ConfigSaveError if key_path is in EPHEMERAL_FIELDS
      KeyError       if key_path doesn't exist in PolilyConfig schema
    """
    if key_path in EPHEMERAL_FIELDS:
        raise ConfigSaveError(
            f"{key_path} has no persisted value to reset"
        )
    defaults = _flatten_pydantic(PolilyConfig())
    if key_path not in defaults:
        raise KeyError(
            f"{key_path} is not a known PolilyConfig leaf"
        )
    upsert(db, key_path, defaults[key_path])


def _rescue_invalid_yaml(yaml_path: Path, reason: str) -> Path | None:
    """Rename a failed-validation config.yaml to config.yaml.bak.

    SF1 (v0.10.0) — without this rescue, the next polily startup would
    yaml-regen over the user's customizations, and they'd never see the
    values they spent time tweaking. Renaming preserves them on disk.

    Returns the .bak path on success, None if rename failed (best-effort).
    Existing .bak file is overwritten — most recent failure wins.
    """
    bak_path = yaml_path.with_suffix(yaml_path.suffix + ".bak")
    try:
        # os.replace semantics — overwrite if present, atomic on POSIX+Win
        yaml_path.replace(bak_path)
        _log.warning(
            "Renamed invalid config.yaml → %s (reason: %s)",
            bak_path.name, reason,
        )
        return bak_path
    except OSError as e:
        _log.warning("Could not rescue config.yaml to .bak: %s", e)
        return None


def _migrate_yaml_to_db(db) -> MigrationStatus:
    """One-shot v0.9.x → v0.10.0 migration (Whis B3).

    **Call-order invariant**: this function MUST be called in the same
    code path as ensure_seeded(), with migration FIRST. Phase 2's
    load_config_from_db() does this correctly. If a future caller
    invokes ensure_seeded() before _migrate_yaml_to_db() in a separate
    process, that process would write Pydantic defaults via INSERT OR
    IGNORE, then this function's count check would see > 0 and skip,
    silently losing the user's legacy yaml customization. The atomic
    "migrate then seed" sequence inside load_config_from_db() prevents
    this race.

    Imports any user-customized values from a legacy `config.yaml` into
    db.config, but ONLY if db.config is currently empty (so on subsequent
    starts the migration becomes a no-op and yaml is overwritten by the
    Phase 3 generator).

    Returns a structured status (SF1 — was previously bare logging that
    went nowhere because no logging.basicConfig was wired):
      - ("ok", N)                          — N leaves migrated successfully
      - ("skipped_no_yaml",)               — fresh install, normal case
      - ("skipped_already_migrated",)      — db.config has rows, idempotent re-run
      - ("skipped_invalid", reason)        — yaml present but failed validation;
                                             original file is renamed to
                                             config.yaml.bak so the user can
                                             manually rescue values

    Skips:
      - EPHEMERAL_FIELDS (always recomputed at runtime)

    Garbled / unreadable yaml: returns ("skipped_invalid", reason) and
    rescues the file as .bak.
    """
    cur = db.conn.execute("SELECT COUNT(*) FROM config")
    if cur.fetchone()[0] > 0:
        status: MigrationStatus = ("skipped_already_migrated",)
        _set_last_migration_status(status)
        return status

    yaml_path = Path("config.yaml")
    if not yaml_path.exists():
        status = ("skipped_no_yaml",)
        _set_last_migration_status(status)
        return status

    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except (yaml.YAMLError, OSError, UnicodeDecodeError) as e:
        reason = f"parse error: {e}"
        _log.warning("Legacy yaml migration skipped (%s)", reason)
        _rescue_invalid_yaml(yaml_path, reason)
        status = ("skipped_invalid", reason)
        _set_last_migration_status(status)
        return status

    if not isinstance(raw, dict) or not raw:
        # Empty / non-dict yaml is "no useful content" — treat as no-yaml.
        # Don't .bak it (nothing to rescue) and don't show a warning.
        status = ("skipped_no_yaml",)
        _set_last_migration_status(status)
        return status

    # Validate by attempting to construct a candidate PolilyConfig.
    # If yaml has dropped fields from older polily versions (e.g.,
    # discipline.* removed in v0.9.5), Pydantic ignores them via
    # extra="ignore" in the model_config; no crash.
    try:
        candidate = PolilyConfig.model_validate(raw)
    except ValidationError as e:
        reason = str(e)
        _log.warning(
            "Legacy yaml migration skipped (invalid values): %s", reason,
        )
        _rescue_invalid_yaml(yaml_path, reason)
        status = ("skipped_invalid", reason)
        _set_last_migration_status(status)
        return status

    flat = _flatten_pydantic(candidate)
    now = datetime.now(UTC).isoformat()
    rows = [
        (key, json.dumps(value), now)
        for key, value in flat.items()
        if key not in EPHEMERAL_FIELDS
    ]
    with db.conn:
        db.conn.executemany(
            "INSERT OR IGNORE INTO config (key_path, value, updated_at) VALUES (?, ?, ?)",
            rows,
        )
    _log.info(
        "Migrated %d leaves from legacy config.yaml into db.config",
        len(rows),
    )
    status = ("ok", len(rows))
    _set_last_migration_status(status)
    return status
