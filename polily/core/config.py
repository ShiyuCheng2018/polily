"""Config loading with deep merge for minimal + full config overlay."""

import copy
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


def _default_user_agent() -> str:
    # Resolved lazily so the HTTP User-Agent always reflects the installed
    # polily version rather than a stale literal (drift bug fixed in v0.9.4
    # — v0.9.0–v0.9.3 shipped with hardcoded `"polily/0.9"` while the package
    # version bumped out from under it).
    from polily import __version__
    return f"polily/{__version__}"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base. Does not mutate inputs."""
    result = {}
    for key in base:
        if key in override:
            if isinstance(base[key], dict) and isinstance(override[key], dict):
                result[key] = deep_merge(base[key], override[key])
            else:
                result[key] = copy.deepcopy(override[key])
        else:
            result[key] = copy.deepcopy(base[key])
    for key in override:
        if key not in base:
            result[key] = copy.deepcopy(override[key])
    return result


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
        default=100.0,
        ge=1.0,
        description="Initial cash when wallet is first created or reset.",
    )


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


def load_config(
    path: Path,
    defaults_path: Path | None = None,
) -> PolilyConfig:
    """Load config from YAML, optionally merging with defaults."""
    if defaults_path is not None:
        with open(defaults_path) as f:
            base_raw = yaml.safe_load(f) or {}
        with open(path) as f:
            override_raw = yaml.safe_load(f) or {}
        merged = deep_merge(base_raw, override_raw)
    else:
        with open(path) as f:
            merged = yaml.safe_load(f) or {}
    return PolilyConfig.model_validate(merged)


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
    with db.conn:
        db.conn.execute("BEGIN IMMEDIATE")
        _migrate_yaml_to_db(db)
        ensure_seeded(db)

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
    """Return the default polily db file path.

    Per Whis SF11 — `archiving.db_file` is HIDDEN_IN_TUI and
    "Pydantic-default-only": even if a row exists in db.config for it,
    we'd need to know the db path BEFORE loading db.config to read
    that row. So all callers (TUI service, CLI reset, daemon startup)
    bootstrap the path from the Pydantic-default value.

    Practically this means archiving.db_file is an install-time config
    (set via env var or post-Phase-7 migration), not a runtime knob —
    its db.config row is informational, not load-bearing.

    Returns:
        Path object for the default db file (typically './data/polily.db').
    """
    return Path(PolilyConfig().archiving.db_file)
