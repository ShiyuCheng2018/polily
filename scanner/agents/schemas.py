"""Pydantic models for AI agent input/output schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

ActionLevel = Literal["BUY_YES", "BUY_NO", "WATCH", "PASS", "HOLD", "SELL", "REDUCE"]
OpportunityType = Literal["instant_mispricing", "short_window", "slow_structure", "watch_only", "no_trade"]
FrictionEdge = Literal["edge_exceeds", "roughly_equals", "friction_exceeds"]
BiasDirection = Literal["YES", "NO", "NONE"]
Strength = Literal["strong", "medium", "weak"]
ResolutionRisk = Literal["low", "medium", "high"]
ResolutionClarity = Literal["clear", "mostly_clear", "ambiguous", "unclear"]
Confidence = Literal["low", "medium", "high"]



# --- Schema types ---

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

    event_id: str

    # Decision
    action: ActionLevel = "PASS"
    bias: BiasDirection | None = "NONE"
    strength: Strength | None = "weak"
    confidence: Confidence = "low"
    opportunity_type: OpportunityType | None = "no_trade"

    # Timing
    time_window: TimeWindow = TimeWindow(urgency="normal", note="")

    # Why
    why_now: str | None = ""
    why_not_now: str | None = ""
    friction_vs_edge: FrictionEdge | None = "friction_exceeds"

    # Risk
    execution_risk: Confidence | None = "low"
    risk_flags: list[RiskFlag] = []
    counterparty_note: str = ""

    # Evidence (split into supporting vs invalidation)
    supporting_findings: list[ResearchFinding] = []
    invalidation_findings: list[ResearchFinding] = []

    # Scheduling — required for ALL actions
    next_check_at: str | None = None      # ISO 8601 — when to recheck this market
    next_check_reason: str = ""           # brief reason for this check time

    # Recheck
    recheck_conditions: list[str] = []

    # Crypto-specific (optional)
    crypto: CryptoContext | None = None

    # Display
    summary: str = ""
    one_line_verdict: str = ""

    model_config = ConfigDict(extra="ignore")

    def semantic_errors(self) -> list[str]:
        """Return list of semantic issues. Empty = OK. Used by retry logic."""
        errors = []
        if self.action in ("BUY_YES", "BUY_NO"):
            if not self.why_now or len((self.why_now or "").strip()) < 10:
                errors.append("action=BUY requires substantive why_now")
            if not self.supporting_findings:
                errors.append("action=BUY requires at least 1 supporting_finding")
        elif self.action in ("HOLD", "SELL", "REDUCE"):
            if not self.why_now or len((self.why_now or "").strip()) < 10:
                errors.append("action=HOLD/SELL/REDUCE requires substantive why_now")
            if self.action == "SELL" and not self.invalidation_findings:
                errors.append("action=SELL requires invalidation_findings (why thesis broke)")
        elif self.action in ("WATCH", "PASS"):
            if not self.why_not_now or len((self.why_not_now or "").strip()) < 10:
                errors.append("action=WATCH/PASS requires substantive why_not_now")
        if not self.next_check_at:
            errors.append("next_check_at is required for all actions")
        if self.action in ("BUY_YES", "BUY_NO", "SELL", "HOLD", "REDUCE"):
            if not self.invalidation_findings:
                errors.append("invalidation_findings must have at least 1 entry")
        if not self.summary or len(self.summary.strip()) < 5:
            errors.append("summary required")
        if not self.one_line_verdict or len(self.one_line_verdict.strip()) < 5:
            errors.append("one_line_verdict required")
        return errors


