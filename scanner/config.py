"""Config loading with deep merge for minimal + full config overlay."""

import copy
from pathlib import Path

import yaml
from pydantic import BaseModel


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
    user_agent: str = "polymarket-scanner/0.1"


class CliConfig(BaseModel):
    default_mode: str = "default"
    tier_b_terminal_limit: int = 5
    show_tier_c_in_terminal: bool = False
    generate_market_links: bool = True
    polymarket_base_url: str = "https://polymarket.com/event/"


class ScannerSection(BaseModel):
    output_dir: str = "./outputs"
    scan_archive_dir: str = "./data/scans"
    max_markets_to_fetch: int = 1000
    include_closed_markets: bool = False
    categories_allowlist: list[str] = []
    categories_blocklist: list[str] = []
    tags_allowlist: list[str] = []
    tags_blocklist: list[str] = []
    two_pass_scan: bool = True
    orderbook_fetch_top_n: int = 50
    recommended_scan_time_utc: str = "14:00"


class FiltersConfig(BaseModel):
    require_binary_market: bool = True
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

    max_spread_pct_yes: float = 0.04
    preferred_max_spread_pct_yes: float = 0.02
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


class ScoringWeights(BaseModel):
    liquidity_structure: int = 30
    objective_verifiability: int = 25
    probability_space: int = 20
    time_structure: int = 15
    trading_friction: int = 10


class ScoringThresholds(BaseModel):
    tier_a_min_score: int = 70
    tier_b_min_score: int = 45
    tier_a_require_mispricing: bool = False


class ScoringConfig(BaseModel):
    weights: ScoringWeights = ScoringWeights()
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
    enabled: bool = True
    fallback_on_error: bool = True
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


class CounterpartyConfig(BaseModel):
    flag_large_trades: bool = True
    large_trade_threshold_usd: float = 500
    flag_book_imbalance: bool = True
    book_imbalance_ratio: float = 3.0


class CalendarConfig(BaseModel):
    enabled: bool = True
    calendar_file: str = "./data/calendar.yaml"
    lookahead_days: int = 3
    cross_domain_linking: bool = True


class PaperTradingConfig(BaseModel):
    enabled: bool = True
    data_file: str = "./data/paper_trades.db"
    default_position_size_usd: float = 20
    assumed_round_trip_friction_pct: float = 0.04
    auto_resolve: bool = False


class DisciplineConfig(BaseModel):
    account_size_usd: float = 150
    max_single_trade_pct: float = 0.13
    max_single_trade_usd: float = 20
    max_concurrent_positions: int = 3
    max_total_exposure_pct: float = 0.40
    max_trades_per_week: int = 5
    pause_threshold_usd: float = 80
    paper_trading_first_days: int = 14


class ReportingConfig(BaseModel):
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
    disclaimer: str = "Scanner output is a research prompt, not a trade recommendation."


class ArchivingConfig(BaseModel):
    enabled: bool = True
    archive_dir: str = "./data/scans"
    db_file: str = "./data/polily.db"
    archive_all_passing: bool = True


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
    enabled: bool = True
    magnitude_threshold: float = 70
    quality_threshold: float = 60
    daily_analysis_limit: int = 10  # max AI analyses per market per day
    rolling_window_hours: int = 6   # baseline window for volume ratio
    poll_intervals: dict[str, int] = {
        "crypto": 10,           # 10s
        "economic_data": 20,    # 20s
        "political": 60,        # 60s
        "sports": 15,           # 15s
        "default": 30,          # 30s
    }
    # Drift detection — rolling window thresholds per market type
    # {market_type: {window_minutes: absolute_change_threshold}}
    drift_windows: dict[str, dict[int, float]] = {
        "crypto": {5: 0.05, 30: 0.08, 60: 0.12, 240: 0.18},
        "political": {5: 0.03, 30: 0.05, 60: 0.08, 240: 0.12},
        "default": {5: 0.03, 30: 0.05, 60: 0.08, 240: 0.12},
    }
    cusum_drift: float = 0.003          # noise filter per tick
    cusum_threshold: float = 0.06       # cumulative trigger level
    drift_cooldown_seconds: int = 3600  # 60 min cooldown for drift-triggered analysis

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


class ScannerConfig(BaseModel):
    """Top-level config model.

    Can be constructed programmatically:
        config = ScannerConfig()  # all defaults
        config = ScannerConfig(discipline=DisciplineConfig(account_size_usd=100))
        config = ScannerConfig.from_dict({"discipline": {"account_size_usd": 100}})
    """

    @classmethod
    def from_dict(cls, data: dict) -> "ScannerConfig":
        """Construct from a plain dict (merges with defaults)."""
        return cls.model_validate(data)

    @classmethod
    def from_defaults(cls) -> "ScannerConfig":
        """Construct with all default values."""
        return cls()

    api: ApiConfig = ApiConfig()
    cli: CliConfig = CliConfig()
    scanner: ScannerSection = ScannerSection()
    filters: FiltersConfig = FiltersConfig()
    heuristics: HeuristicsConfig = HeuristicsConfig()
    scoring: ScoringConfig = ScoringConfig()
    market_types: dict[str, MarketTypeConfig] = {}
    ai: AiConfig = AiConfig()
    mispricing: MispricingConfig = MispricingConfig()
    counterparty: CounterpartyConfig = CounterpartyConfig()
    calendar: CalendarConfig = CalendarConfig()
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    discipline: DisciplineConfig = DisciplineConfig()
    reporting: ReportingConfig = ReportingConfig()
    archiving: ArchivingConfig = ArchivingConfig()
    execution_hints: ExecutionHintsConfig = ExecutionHintsConfig()
    movement: MovementConfig = MovementConfig()


def load_config(
    path: Path,
    defaults_path: Path | None = None,
) -> ScannerConfig:
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
    return ScannerConfig.model_validate(merged)
