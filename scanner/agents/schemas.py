"""Pydantic models for AI agent input/output schemas."""

from typing import Literal

from pydantic import BaseModel, Field

SuggestedStyle = Literal["research_candidate", "watch_only", "research_repricing", "avoid_despite_score"]
ActionLevel = Literal["worth_research", "small_position_ok", "watch_only", "avoid"]
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


class BiasOutput(BaseModel):
    """Direction bias (conditional advice, only in --lean mode)."""
    direction: Literal["lean_yes", "lean_no", "neutral"]
    reasoning: str
    confidence: Confidence
    caveat: str  # "前提是 BTC 维持当前波动率"


class NarrativeWriterOutput(BaseModel):
    """Output from Agent 2: NarrativeWriter (decision advisor mode)."""

    market_id: str

    # Decision layer
    action: ActionLevel = "watch_only"
    action_reasoning: str = ""
    confidence: Confidence = "low"

    # Time window
    time_window: TimeWindow = TimeWindow(urgency="normal", note="")
    friction_impact: str = ""

    # Reasoning layer
    summary: str
    risk_flags: list[RiskFlag] = []
    counterparty_note: str = ""

    # Research findings (replaces research_checklist)
    research_findings: list[ResearchFinding] = []
    research_checklist: list[str] = []  # deprecated, kept for old data compat

    # Direction bias (optional, only in --lean mode)
    bias: BiasOutput | None = None

    # Verdict
    one_line_verdict: str = ""
    suggested_style: SuggestedStyle = "watch_only"  # kept for backward compat


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
