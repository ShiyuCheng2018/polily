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
    provider: str = "polymarket"
    request_timeout_seconds: int = 20
    max_retries: int = 3
    backoff_seconds: float = 1.5
    use_cache: bool = True
    cache_dir: str = "./data/cache"
    user_agent: str = Field(default_factory=_default_user_agent)


class CliConfig(BaseModel):
    default_mode: str = "default"
    tier_b_terminal_limit: int = 5
    show_tier_c_in_terminal: bool = False
    generate_market_links: bool = True
    polymarket_base_url: str = "https://polymarket.com/event/"


class FiltersConfig(BaseModel):
    require_objective_market: bool = True
    require_clear_rules: bool = False
    require_named_resolution_source: bool = False

    min_yes_price: float = 0.20
    max_yes_price: float = 0.80
    hard_reject_below_yes_price: float = 0.15
    hard_reject_above_yes_price: float = 0.85
    preferred_min_yes_price: float = 0.30
    preferred_max_yes_price: float = 0.70

    min_days_to_resolution: float = 0.5
    max_days_to_resolution: float = 14
    preferred_min_days_to_resolution: float = 0.5
    preferred_max_days_to_resolution: float = 7

    # Spread threshold applies to the best-side % (cheaper of YES vs NO), so
    # a low-YES market with a tradeable NO side isn't rejected for YES-side
    # math the user never actually pays.
    max_spread_pct: float = 0.04
    preferred_max_spread_pct: float = 0.02
    max_round_trip_friction_pct: float = 0.08

    min_volume: float = 1000
    min_open_interest: float = 1000

    min_bid_depth_usd: float = 100
    max_slippage_at_20usd: float = 0.02

    reject_ultra_short_noise_markets: bool = True
    reject_long_dated_narrative_markets: bool = True
    long_dated_narrative_days_cutoff: float = 30

    flag_uma_only_resolution: bool = True
    reject_high_resolution_risk: bool = False


class HeuristicsConfig(BaseModel):
    objective_whitelist_keywords: list[str] = []
    objective_blacklist_keywords: list[str] = []
    noise_market_keywords: list[str] = []
    noise_max_days: float = 0.1
    noise_categories: list[str] = []
    narrative_market_keywords: list[str] = []
    resolution_source_bonus_keywords: list[str] = []


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


class MarketTypeConfig(BaseModel):
    keywords: list[str] = []
    scoring_overrides: dict[str, int] = {}
    mispricing_enabled: bool = False
    note: str | None = None


class AgentConfig(BaseModel):
    enabled: bool = True
    model: str = "sonnet"
    max_concurrent: int = 3
    timeout_seconds: int = 60
    max_candidates: int = 15  # max markets to AI-analyze per scan


class AiConfig(BaseModel):
    cli_command: str = "claude"
    narrative_writer: AgentConfig = AgentConfig(model="sonnet", max_candidates=8, max_concurrent=2, timeout_seconds=300)


class CryptoMispricingConfig(BaseModel):
    price_source: str = "binance"
    volatility_lookback_days: int = 30
    min_deviation_pct: float = 0.08
    prefer_implied_vol: bool = True


class MultiOutcomeConfig(BaseModel):
    enabled: bool = True
    max_sum_deviation: float = 0.10


class MispricingConfig(BaseModel):
    enabled: bool = True
    crypto: CryptoMispricingConfig = CryptoMispricingConfig()
    multi_outcome: MultiOutcomeConfig = MultiOutcomeConfig()


class PaperTradingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    enabled: bool = True
    default_position_size_usd: float = 20
    assumed_round_trip_friction_pct: float = 0.04


class ReportingConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    write_json: bool = True
    write_csv: bool = True
    write_terminal_summary: bool = True
    include_score_breakdown: bool = True
    include_risk_flags: bool = True
    include_why_it_passed: bool = True
    include_friction_estimate: bool = True
    include_counterparty_note: bool = True
    include_mispricing_signal: bool = True
    include_worst_case_loss: bool = True
    include_net_edge_after_friction: bool = True
    include_discipline_status: bool = True
    disclaimer: str = "Polily output is a research prompt, not a trade recommendation."


class ArchivingConfig(BaseModel):
    enabled: bool = True
    db_file: str = "./data/polily.db"


class WalletConfig(BaseModel):
    """Wallet starting balance for v0.6.0 paper trading system."""
    starting_balance: float = Field(
        default=100.0,
        ge=1.0,
        description="Initial cash when wallet is first created or reset.",
    )


class ExecutionHintsConfig(BaseModel):
    small_account_mode: bool = True
    default_trade_style: str = "research_candidate"
    suggest_manual_review_only: bool = True
    suggest_auto_trading: bool = False
    friction_floor_pct: float = 0.04
    # Conditional advice ("if you're bullish, this may have edge") — off by default, enable with --lean
    show_conditional_advice: bool = False


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
    cli: CliConfig = CliConfig()
    filters: FiltersConfig = FiltersConfig()
    heuristics: HeuristicsConfig = HeuristicsConfig()
    scoring: ScoringConfig = ScoringConfig()
    market_types: dict[str, MarketTypeConfig] = {}
    ai: AiConfig = AiConfig()
    mispricing: MispricingConfig = MispricingConfig()
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    reporting: ReportingConfig = ReportingConfig()
    archiving: ArchivingConfig = ArchivingConfig()
    wallet: WalletConfig = Field(default_factory=WalletConfig)
    execution_hints: ExecutionHintsConfig = ExecutionHintsConfig()
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
