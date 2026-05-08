"""Pydantic config models + db-canonical config loader.

Yaml is no longer a config input as of v0.10.0 — `db.config` is the
canonical source. The yaml file (``config.yaml``) is regenerated
read-only by every polily startup (see ``polily/core/config_yaml.py``)
and exists purely as a human-readable export.
"""

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _default_user_agent() -> str:
    # Resolved lazily so the HTTP User-Agent always reflects the installed
    # polily version rather than a stale literal (drift bug fixed in v0.9.4
    # — v0.9.0–v0.9.3 shipped with hardcoded `"polily/0.9"` while the package
    # version bumped out from under it).
    from polily import __version__
    return f"polily/{__version__}"


# --- Pydantic config models ---


class ApiConfig(BaseModel):
    request_timeout_seconds: int = 20
    user_agent: str = Field(default_factory=_default_user_agent)


class ScoringThresholds(BaseModel):
    tier_a_min_score: int = 70
    tier_b_min_score: int = 45
    tier_a_require_mispricing: bool = False


class ScoringConfig(BaseModel):
    """Structure-score config — only thresholds remain configurable.

    Per-dimension weights live in `polily/scan/scoring.py`'s
    `_TYPE_WEIGHTS` and `_DEFAULT_WEIGHTS` module constants because they
    are tightly coupled with the scoring algorithm and not user-tunable.
    """
    thresholds: ScoringThresholds = ScoringThresholds()


class AgentConfig(BaseModel):
    """Per-agent runtime config — only fields actually consumed.

    Phase 0 (2026-04-25): removed unused `enabled`, `max_concurrent`,
    `max_candidates` fields (zero production consumers per audit).
    """
    model: str = "sonnet"
    timeout_seconds: int = 120
    max_prompt_chars: int = 5000  # truncation threshold for tool-mode prompts (was DEFAULT_MAX_PROMPT_CHARS in agents/base.py)


class AiConfig(BaseModel):
    """AI agent runtime config.

    Phase 0 (2026-04-25): removed dead `cli_command` field (set in
    config but never threaded into BaseAgent constructor; BaseAgent
    has its own POLILY_CLAUDE_CLI env var → 'claude' fallback chain).
    """
    narrative_writer: AgentConfig = AgentConfig(model="sonnet", timeout_seconds=300)


class TuiConfig(BaseModel):
    """TUI runtime config — UI behavior knobs.

    Phase 0 (2026-04-25) introduced this section to lift hardcoded UI
    constants (e.g., HEARTBEAT_SECONDS) out of view files. Will accumulate
    additional TUI-only knobs (theme, font, refresh intervals) in future
    PRs.
    """
    heartbeat_seconds: float = 5.0  # interval for bus_heartbeat refresh tick
    language: str = "en"  # default UI language (BCP-47-ish code, e.g. "en"/"zh"); only used at startup when DB user_prefs.language is unset


class CryptoMispricingConfig(BaseModel):
    volatility_lookback_days: int = 30
    min_deviation_pct: float = 0.08


class MultiOutcomeConfig(BaseModel):
    enabled: bool = True
    max_sum_deviation: float = 0.10


class MispricingConfig(BaseModel):
    enabled: bool = True
    crypto: CryptoMispricingConfig = CryptoMispricingConfig()
    multi_outcome: MultiOutcomeConfig = MultiOutcomeConfig()


class ArchivingConfig(BaseModel):
    db_file: str = "./data/polily.db"


class WalletConfig(BaseModel):
    """Wallet starting balance for v0.6.0 paper trading system."""
    starting_balance: float = Field(
        default=1000.0,
        ge=1.0,
        description="Initial cash when wallet is first created or reset.",
    )


class UpdateCheckConfig(BaseModel):
    """v0.11.4: state for the TUI's "new version available" indicator.

    Storage-only knob — not user-tunable. The dismissed_version is
    persisted via config_store.upsert when user clicks 更新日志 sidebar.
    Listed in HIDDEN_IN_TUI so it doesn't appear in ⚙ 配置 UI.

    Default empty string (not None) because config_store._flatten_pydantic
    rejects None-valued leaves (SF9 guard). Empty string treated as
    "never dismissed" by update_check module.
    """
    last_dismissed_version: str = ""


class MovementWeights(BaseModel):
    """Per-market-type signal weights for magnitude and quality."""
    magnitude: dict[str, float] = {}
    quality: dict[str, float] = {}


class MovementConfig(BaseModel):
    """Movement scorer config for AI-trigger decisions.

    Phase 0 (2026-04-25) cleanup: removed dead `enabled`,
    `rolling_window_hours`, `cusum_drift`, `cusum_threshold`,
    `drift_cooldown_seconds`, `drift_windows` fields. The drift
    detector module (polily/monitor/drift.py) is deleted in the same
    commit; movement scoring in scorer.py is the sole movement signal
    pipeline post-v0.7.

    `enabled` was removed because no production code path checks
    `if config.movement.enabled:` — movement is unconditionally on
    whenever the daemon runs. If a future user wants an off-switch,
    re-add as a wired-up gate, not a silent flag.
    """
    magnitude_threshold: float = 70
    quality_threshold: float = 60
    daily_analysis_limit: int = 10  # max AI analyses per market per day
    min_history_entries: int = 5  # min movement_log rows before scoring kicks in (was poll_job _MIN_HISTORY)
    stale_threshold_seconds: int = 600  # data older than this skipped (was poll_job _STALE_SECONDS)

    # Note: open_interest_delta and correlated_asset_move removed —
    # Polymarket CLOB API does not expose per-poll OI or correlated assets.
    # Weights redistributed to computable signals (all groups sum to 1.0).
    weights: dict[str, MovementWeights] = {
        "crypto": MovementWeights(
            magnitude={"price_z_score": 0.15, "book_imbalance": 0.10,
                       "fair_value_divergence": 0.40, "underlying_z_score": 0.20, "cross_divergence": 0.15},
            quality={"volume_ratio": 0.40, "trade_concentration": 0.35, "volume_price_confirmation": 0.25},
        ),
        "political": MovementWeights(
            magnitude={"price_z_score": 0.35, "book_imbalance": 0.25,
                       "sustained_drift": 0.40},
            quality={"volume_ratio": 0.35, "trade_concentration": 0.40, "volume_price_confirmation": 0.25},
        ),
        "economic_data": MovementWeights(
            magnitude={"price_z_score": 0.30, "book_imbalance": 0.15,
                       "time_decay_adjusted_move": 0.55},
            quality={"volume_ratio": 0.40, "trade_concentration": 0.30, "volume_price_confirmation": 0.30},
        ),
        "default": MovementWeights(
            magnitude={"price_z_score": 0.45, "book_imbalance": 0.30,
                       "volume_ratio": 0.25},
            quality={"volume_ratio": 0.40, "trade_concentration": 0.35, "volume_price_confirmation": 0.25},
        ),
    }


class PolilyConfig(BaseModel):
    """Top-level config model.

    Can be constructed programmatically:
        config = PolilyConfig()  # all defaults
        config = PolilyConfig(wallet=WalletConfig(starting_balance=200.0))
        config = PolilyConfig.from_dict({"wallet": {"starting_balance": 200.0}})
    """

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def from_dict(cls, data: dict) -> "PolilyConfig":
        """Construct from a plain dict (merges with defaults)."""
        return cls.model_validate(data)

    @classmethod
    def from_defaults(cls) -> "PolilyConfig":
        """Construct with all default values."""
        return cls()

    api: ApiConfig = ApiConfig()
    scoring: ScoringConfig = ScoringConfig()
    ai: AiConfig = AiConfig()
    tui: TuiConfig = TuiConfig()
    mispricing: MispricingConfig = MispricingConfig()
    archiving: ArchivingConfig = ArchivingConfig()
    wallet: WalletConfig = Field(default_factory=WalletConfig)
    movement: MovementConfig = MovementConfig()
    update_check: UpdateCheckConfig = Field(default_factory=UpdateCheckConfig)

    # v0.12.0: which strategy the NarrativeWriter agent uses for analyses.
    # 'official' = packaged polily/strategies/default.md
    # 'user'     = user_strategy.text (set via TUI 7 策略 page)
    # Hot-swap takes effect on the next analysis dispatch; in-flight analyses
    # finish with the previously-selected strategy.
    active_strategy: Literal["official", "user"] = "official"


class ConfigValidationError(Exception):
    """Raised when db.config contains values that fail Pydantic validation.

    Per design §7.3 — surfaced as a fatal screen by TUI / exit(1) by daemon.
    Not auto-recoverable; user must run `polily config reset --all` (or single
    key) to escape.
    """


def load_config_from_db(db) -> PolilyConfig:
    """Load config from db.config (the canonical source).

    Per design §4.2 + Phase 2 AC1 + AC3:

    1. Migrate legacy yaml → db (Whis B3) BEFORE seeding defaults — runs once
       (db.config empty), no-op afterward
    2. INSERT OR IGNORE Pydantic defaults to fill any leaves not in db
    3. Steps 1+2 wrapped in BEGIN IMMEDIATE so the cross-process race window
       (process A migrates while process B seeds → user yaml loss) is closed
       (AC1)
    4. Read all rows + filter EPHEMERAL_FIELDS defensively
    5. Pydantic validate; ConfigValidationError on failure — no fallback (AC3)

    Caller responsibilities:
      - TUI (polily.tui.app): catch ConfigValidationError → push FatalConfigScreen (Phase 7)
      - daemon (polily.cli.run_scheduler_daemon): catch ConfigValidationError → exit(1)
    """
    from polily.core.config_store import (
        EPHEMERAL_FIELDS,
        _migrate_yaml_to_db,
        _unflatten,
        ensure_seeded,
        load_all,
    )

    # AC1: write-locked transaction prevents cross-process interleaving
    # of migrate count-check vs seed insert. Without BEGIN IMMEDIATE, two
    # processes both see count=0 → process B's seed writes defaults →
    # process A's migrate INSERT OR IGNORE no-ops user yaml values silently.
    #
    # SF6 (v0.10.0): explicit BEGIN IMMEDIATE / commit / rollback rather
    # than `with db.conn:` wrapping. Python's default isolation_level
    # opens an implicit transaction inside `with db.conn:`, then issuing
    # `BEGIN IMMEDIATE` inside is either a no-op or — on stricter sqlite
    # builds — `OperationalError: cannot start a transaction within a
    # transaction`. Explicit control sidesteps both ambiguity and the
    # nested-with confusion (ensure_seeded itself uses `with db.conn:`).
    #
    # v0.11.6 §1.5.1 carve-out: BEGIN IMMEDIATE retained — cross-process
    # race protection requires immediate-mode at TXN start, not on first
    # write. db.transaction() (deferred mode) only promotes to immediate
    # at FIRST WRITE, leaving the SELECT-then-INSERT race window open
    # for competitor processes. Wrapped in `with db._lock:` for thread
    # safety; transaction code unchanged.
    with db._lock:
        db.conn.execute("BEGIN IMMEDIATE")
        try:
            _migrate_yaml_to_db(db)
            ensure_seeded(db)
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise

    flat = load_all(db)
    # Defensive — even if user manually inserted EPHEMERAL_FIELDS rows via
    # raw SQL, ignore them at validate time so default_factory wins.
    flat = {k: v for k, v in flat.items() if k not in EPHEMERAL_FIELDS}
    nested = _unflatten(flat)

    try:
        return PolilyConfig.model_validate(nested)
    except Exception as e:
        # AC3: fail-loud. Wrap Pydantic ValidationError so callers don't
        # leak Pydantic internals.
        raise ConfigValidationError(str(e)) from e


def default_db_path() -> Path:
    """Return the polily db file path, resolved via the paths module.

    v0.11.0 BREAKING: this used to read the Pydantic default
    `archiving.db_file = "./data/polily.db"`, which was cwd-relative
    and broke any non-developer install method (pipx, brew, binary).

    Now delegates to ``polily.core.paths.db_path()`` which respects the
    3-layer resolver (CLI flag > POLILY_DATA_DIR env > platformdirs
    default). The Pydantic `archiving.db_file` knob remains in
    PolilyConfig for forward-compat (HIDDEN_IN_TUI) but is now
    informational only; no production code path reads it.

    Returns:
        Absolute Path to the db file. Parent directory is auto-created
        on first access via paths.data_dir()'s lazy mkdir.
    """
    from polily.core import paths
    return paths.db_path()


def _unwrap_annotation(ann):
    """Strip Optional[X] → X and Annotated[X, ...] → X.

    Repeated until neither wrapping applies. Generic Union[X, Y] (multiple
    non-None args) is returned as-is; ``_coerce_value`` will raise the
    ``不支持的类型`` error which is the right behavior — config knobs
    aren't supposed to be sum types.

    SF8 (v0.10.0): added so live validation in the TUI Edit modal still
    works after a future schema-evolution slap of ``Optional[int]`` or
    ``Annotated[float, Field(ge=1.0)]`` on a leaf. Without this, those
    wrappings would fall through to ``_coerce_value`` and hit the
    ``不支持的类型`` branch even when the underlying scalar is coercible.
    """
    import typing as _t

    while True:
        # Annotated[X, metadata...] (PEP 593)
        if hasattr(ann, "__metadata__"):
            ann = _t.get_args(ann)[0]
            continue
        # Optional[X] = Union[X, None] — unwrap only when exactly one
        # non-None arg remains (i.e. genuine Optional, not generic Union).
        origin = _t.get_origin(ann)
        if origin is _t.Union:
            args = [a for a in _t.get_args(ann) if a is not type(None)]
            if len(args) == 1:
                ann = args[0]
                continue
        # Literal[v1, v2, ...] — when every value is the same scalar type,
        # fold to that scalar. Pydantic still rejects invalid values at
        # `model_validate` time (the Literal constraint is enforced by the
        # field, not by `_coerce_value`); we just need a coercible scalar
        # for raw-input parsing in the TUI Edit modal. (v0.12.0 — added
        # for `active_strategy: Literal["official", "user"]`.)
        if origin is _t.Literal:
            args = _t.get_args(ann)
            if args and all(isinstance(a, type(args[0])) for a in args):
                ann = type(args[0])
                continue
        return ann


def _resolve_field_annotation(key_path: str):
    """Walk PolilyConfig schema to find the type annotation for a key_path.

    For nested dict[str, BaseModel] (e.g. movement.weights.crypto.magnitude.X)
    descends into the dict's value type. For dict[str, scalar] returns the
    scalar value type. Returns None if the key doesn't resolve.

    Optional[X] / Annotated[X, ...] wrappings are stripped via
    ``_unwrap_annotation`` at every annotation read (SF8).

    Used by Edit modal live validation — coerce raw input to the right type
    before attempting full PolilyConfig.model_validate().
    """
    import typing as _t

    parts = key_path.split(".")
    cursor: Any = PolilyConfig

    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1

        # Resolve cursor → field type
        if isinstance(cursor, type) and issubclass(cursor, BaseModel):
            field = cursor.model_fields.get(part)
            if field is None:
                return None
            cursor = _unwrap_annotation(field.annotation)
            if is_last:
                return cursor
            continue

        # cursor is dict[str, X] or dict[str, dict[str, X]] — unwrap one level.
        origin = _t.get_origin(cursor)
        if origin is dict:
            args = _t.get_args(cursor)
            if len(args) >= 2:
                cursor = _unwrap_annotation(args[1])
                if isinstance(cursor, type) and issubclass(cursor, BaseModel):
                    continue
                inner_origin = _t.get_origin(cursor)
                if inner_origin is dict:
                    inner_args = _t.get_args(cursor)
                    if len(inner_args) >= 2:
                        cursor = _unwrap_annotation(inner_args[1])
                if is_last:
                    return cursor
                continue
        return None

    return cursor


def _coerce_value(raw: str, annotation):
    """Try to parse `raw` as `annotation`. Raises ValueError on failure."""
    if annotation is bool:
        if raw.lower() in ("true", "1", "yes", "on"):
            return True
        if raw.lower() in ("false", "0", "no", "off"):
            return False
        raise ValueError(f"无法解析 {raw!r} 为 bool")
    if annotation is int:
        try:
            return int(raw)
        except ValueError as e:
            raise ValueError(f"无法解析 {raw!r} 为 int") from e
    if annotation is float:
        try:
            return float(raw)
        except ValueError as e:
            raise ValueError(f"无法解析 {raw!r} 为 float") from e
    if annotation is str:
        return raw
    raise ValueError(f"不支持的类型 {annotation!r}")


def save_knob(db, key_path: str, new_value: Any) -> None:
    """Validate and persist a single config knob change.

    Per design §4.2 + §7.2 + Whis SF8:
      1. Read current db.config rows directly (no double round-trip
         through load_config_from_db → _flatten_pydantic)
      2. Apply new_value to the flat dict
      3. Filter EPHEMERAL_FIELDS (defensive — they're not in db anyway)
      4. Pydantic validate — raises ConfigValidationError on failure
      5. Only after validation passes, upsert into db

    Used by TUI Edit modal save handler. EPHEMERAL_FIELDS rejection happens
    inside config_store.upsert (defense-in-depth).
    """
    from polily.core.config_store import (
        EPHEMERAL_FIELDS,
        _unflatten,
        load_all,
        upsert,
    )

    flat = load_all(db)  # already filters EPHEMERAL_FIELDS, returns dict
    flat[key_path] = new_value
    # Defensive — even if a future caller pre-populates flat differently
    flat = {k: v for k, v in flat.items() if k not in EPHEMERAL_FIELDS}
    try:
        PolilyConfig.model_validate(_unflatten(flat))
    except Exception as e:
        raise ConfigValidationError(str(e)) from e
    upsert(db, key_path, new_value)


def save_knob_batch(db, updates: dict[str, Any]) -> None:
    """Validate and persist multiple config knob changes atomically.

    Used by `WeightFamilyEditModal` (Round 4) where editing one weight
    leaf in isolation would silently break the algorithmic `sum == 1.0`
    invariant — the whole family must be committed together.

    Contract:
      - All upserts succeed together OR rollback together. If Pydantic
        rejects the merged config, NO row is changed (atomicity).
      - Single `PolilyConfig.model_validate` over the merged config
        (not N validations).
      - Each key MUST be in TERRITORY_A. EPHEMERAL_FIELDS rejected by
        upsert (`ConfigSaveError`); HIDDEN_IN_TUI rejected here
        (`ValueError`). Both gate before the transaction opens so a
        bad input never even starts a write.
      - Empty dict is a no-op (no transaction churn).

    Note: the `sum == 1` invariant on `movement.weights.<type>.<family>.*`
    is enforced at the modal save-time, NOT inside Pydantic — so a
    partial-family write that drifts the sum is allowed at the API
    level. The modal won't issue one; a future caller might.
    """
    from polily.core.config_store import (
        EPHEMERAL_FIELDS,
        _unflatten,
        is_territory_a,
        load_all,
    )

    if not updates:
        return  # no-op — avoid empty BEGIN/COMMIT and a redundant validate.

    # Defense-in-depth: every key in `updates` must be TUI-editable.
    # `upsert` re-checks EPHEMERAL_FIELDS internally, but a HIDDEN_IN_TUI
    # key would slip through that check (it's persisted in db, just not
    # exposed in the TUI). Block here before opening the transaction.
    for key_path in updates:
        if not is_territory_a(key_path):
            raise ValueError(
                f"{key_path} is not editable (HIDDEN_IN_TUI or EPHEMERAL)",
            )

    flat = load_all(db)  # already filters EPHEMERAL_FIELDS
    flat.update(updates)
    # Defensive — even if a future caller mutates flat differently.
    flat = {k: v for k, v in flat.items() if k not in EPHEMERAL_FIELDS}

    # Single merged validation — exactly one model_validate call regardless
    # of how many leaves changed.
    try:
        PolilyConfig.model_validate(_unflatten(flat))
    except Exception as e:
        raise ConfigValidationError(str(e)) from e

    # All-or-nothing write. `upsert` itself uses `with db.conn:` (an
    # implicit transaction commit per call); wrapping multiple upserts in
    # an outer BEGIN IMMEDIATE / COMMIT does NOT nest cleanly with
    # sqlite3's default isolation_level — the inner `with db.conn:` would
    # try to commit mid-batch. So we drive the cursor directly here, in a
    # single explicit transaction (mirrors the SF6 pattern in
    # `load_config_from_db`).
    import json
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    # v0.11.6 §1.5.1 carve-out: same BEGIN IMMEDIATE rationale as the
    # load_config_from_db block above. Wrapped in `with db._lock:` for
    # thread safety; transaction code unchanged.
    with db._lock:
        db.conn.execute("BEGIN IMMEDIATE")
        try:
            for key_path, value in updates.items():
                db.conn.execute(
                    """
                    INSERT INTO config (key_path, value, updated_at) VALUES (?, ?, ?)
                    ON CONFLICT(key_path) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key_path, json.dumps(value), now),
                )
            db.conn.commit()
        except Exception:
            db.conn.rollback()
            raise

    # `upsert` is intentionally NOT used inside the transaction (its
    # `with db.conn:` context manager would conflict). The
    # ConfigSaveError gate it carries for EPHEMERAL_FIELDS is replicated
    # by `is_territory_a` above — territory A excludes EPHEMERAL_FIELDS
    # by construction. Defense-in-depth without the nested-with hazard.
