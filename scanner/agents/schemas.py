"""Pydantic models for AI agent input/output schemas."""

from typing import Literal

from pydantic import BaseModel, Field

SuggestedStyle = Literal["research_candidate", "watch_only", "research_repricing", "avoid_despite_score"]
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


class NarrativeWriterOutput(BaseModel):
    """Output from Agent 2: NarrativeWriter."""

    market_id: str
    summary: str
    why_it_passed: list[str]
    risk_flags: list[str]
    counterparty_note: str
    resolution_risk_note: str | None = None
    research_checklist: list[str]
    suggested_style: SuggestedStyle = "watch_only"
    one_line_verdict: str


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
