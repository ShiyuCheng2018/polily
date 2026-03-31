"""Pydantic models for AI agent input/output schemas."""

from typing import Literal

from pydantic import BaseModel, Field

SuggestedStyle = Literal["research_candidate", "watch_only", "research_repricing", "avoid_despite_score"]
ActionLevel = Literal["BUY_YES", "BUY_NO", "WATCH", "PASS"]
OpportunityType = Literal["instant_mispricing", "short_window", "slow_structure", "watch_only", "no_trade"]
FrictionEdge = Literal["edge_exceeds", "roughly_equals", "friction_exceeds"]
BiasDirection = Literal["YES", "NO", "NONE"]
Strength = Literal["strong", "medium", "weak"]
ResolutionRisk = Literal["low", "medium", "high"]
ResolutionClarity = Literal["clear", "mostly_clear", "ambiguous", "unclear"]
Confidence = Literal["low", "medium", "high"]


class MarketAnalystOutput(BaseModel):
    """Output from Agent 1: MarketAnalyst."""

    market_id: str
    objectivity_score: int = Field(ge=0, le=100)
    objectivity_reasoning: str
    has_catalyst: bool
    catalyst_description: str | None = None
    catalyst_type: str | None = None
    market_type: str
    market_type_confidence: Confidence = "medium"
    resolution_source: str | None = None
    resolution_clarity: ResolutionClarity = "unclear"
    resolution_edge_cases: list[str] = []
    resolution_risk: ResolutionRisk = "medium"
    is_noise_market: bool = False
    flags: list[str] = []


# --- Phase 1 new types ---

class TimeWindow(BaseModel):
    """Time urgency and optimal entry timing."""
    urgency: Literal["urgent", "normal", "no_rush"]
    note: str  # "还剩 2.3 天结算，催化剂在 1 天后"
    optimal_entry: str | None = None  # "建议在 CPI 发布前入场" or None


class RiskFlag(BaseModel):
    """Risk item with severity level."""
    text: str
    severity: Literal["critical", "warning", "info"]


class ResearchFinding(BaseModel):
    """A finding from agent's own research (not a checklist for user)."""
    finding: str  # "BTC 过去 24h 下跌 3.2%"
    source: str  # "Binance"
    impact: str  # "距离阈值更远，YES 概率下降"


class CryptoContext(BaseModel):
    """Crypto-specific analysis fields."""
    distance_to_threshold_pct: float | None = None
    buffer_pct: float | None = None
    daily_vol_pct: float | None = None
    buffer_conclusion: str = ""  # "thin" / "adequate" / "wide"
    market_already_knows: str = ""  # gray auxiliary info


class WatchCondition(BaseModel):
    """Structured conditions for re-evaluating a watched market."""
    watch_reason: str = ""          # "当前价格没有优势，但市场结构值得盯"
    better_entry: str = ""          # "YES <= 0.58"
    trigger_event: str = ""         # "BTC 与阈值距离扩大到 2% 以上"
    invalidation: str = ""          # "距结算 <12h 且价格未变"


class PositionAdvice(BaseModel):
    """Output for position management analysis (from position advisor agent)."""
    advice: Literal["hold", "reduce", "exit"]
    reasoning: str
    thesis_intact: bool = True
    thesis_note: str = ""
    exit_price: str | None = None
    risk_note: str = ""
    research_findings: list["ResearchFinding"] = []


class NarrativeWriterOutput(BaseModel):
    """Output from unified AI analysis — decision assistant mode."""

    market_id: str

    # Decision
    action: ActionLevel = "PASS"
    bias: BiasDirection = "NONE"
    strength: Strength = "weak"
    confidence: Confidence = "low"
    opportunity_type: OpportunityType = "no_trade"

    # Timing
    time_window: TimeWindow = TimeWindow(urgency="normal", note="")

    # Why
    why_now: str = ""
    why_not_now: str = ""
    friction_vs_edge: FrictionEdge = "friction_exceeds"

    # Risk
    execution_risk: Confidence = "low"  # reuse low/medium/high
    risk_flags: list[RiskFlag] = []
    counterparty_note: str = ""

    # Evidence (split into supporting vs invalidation)
    supporting_findings: list[ResearchFinding] = []
    invalidation_findings: list[ResearchFinding] = []

    # Watch / recheck
    recheck_conditions: list[str] = []
    watch: WatchCondition | None = None
    next_step: str = ""

    # Crypto-specific (optional)
    crypto: CryptoContext | None = None

    # Legacy compat
    summary: str = ""
    one_line_verdict: str = ""
    research_findings: list[ResearchFinding] = []  # deprecated, use supporting+invalidation
    research_checklist: list[str] = []  # deprecated
    action_reasoning: str = ""  # deprecated, use why_now/why_not_now
    friction_impact: str = ""  # deprecated, use friction_vs_edge
    why_not_opportunity: list[str] = []  # deprecated, use why_not_now
    suggested_style: SuggestedStyle = "watch_only"  # deprecated


class BriefingOutput(BaseModel):
    """Output from Agent 3: BriefingAnalyst."""

    market_narrative: str
    tracking_insights: list[str]
    paper_trade_observations: str | None = None
    upcoming_focus: str
    action_summary: str


ImpactDirection = Literal["positive_for_yes", "negative_for_yes", "uncertain"]


class CrossDomainOutput(BaseModel):
    """Output from Agent 4: CrossDomainInsight."""

    market_id: str
    event_name: str
    cross_domain_link: str
    impact_direction: ImpactDirection = "uncertain"
    confidence: Confidence = "low"
    research_note: str


class ReviewOutput(BaseModel):
    """Output from Agent 5: ReviewAnalyst."""

    behavior_analysis: str
    category_insights: list[str]
    calibration_feedback: str
    recommendations: list[str]
