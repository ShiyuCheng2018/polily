"""Pydantic models for AI agent input/output schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# --- Shared types ---

AnalysisMode = Literal["discovery", "position_management"]
Confidence = Literal["low", "medium", "high"]

# Discovery actions
DiscoveryAction = Literal["BUY_YES", "BUY_NO", "WATCH", "PASS"]
# Position management actions
PositionAction = Literal["HOLD", "BUY_YES", "BUY_NO", "SELL_YES", "SELL_NO", "REDUCE_YES", "REDUCE_NO"]

FrictionEdge = Literal["edge_exceeds", "roughly_equals", "friction_exceeds"]
ThesisStatus = Literal["intact", "weakened", "broken"]


# --- Sub-schemas ---

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
    """A finding from agent's own research."""
    finding: str  # "BTC 过去 24h 下跌 3.2%"
    source: str  # "Binance"
    impact: str  # "距离阈值更远，YES 概率下降"


class CryptoContext(BaseModel):
    """Crypto-specific analysis fields."""
    distance_to_threshold_pct: float | None = None
    buffer_pct: float | None = None
    daily_vol_pct: float | None = None
    buffer_conclusion: str = ""  # "thin" / "adequate" / "wide"
    market_already_knows: str = ""


class PositionAdvice(BaseModel):
    """Output for position management analysis (from position advisor agent)."""
    advice: Literal["hold", "reduce", "exit"]
    reasoning: str
    thesis_intact: bool = True
    thesis_note: str = ""
    exit_price: str | None = None
    risk_note: str = ""
    research_findings: list["ResearchFinding"] = []


# --- Main output schema ---

class NarrativeWriterOutput(BaseModel):
    """Unified AI analysis output — discovery + position management mode."""

    event_id: str
    mode: AnalysisMode = "discovery"

    # Decision
    action: str = "PASS"  # DiscoveryAction | PositionAction
    confidence: Confidence = "low"

    # Timing
    time_window: TimeWindow = TimeWindow(urgency="normal", note="")

    # Why
    why: str = ""  # core reasoning
    why_not: str | None = None  # why NOT to act (for WATCH/PASS)

    # Evidence
    supporting_findings: list[ResearchFinding] = []
    invalidation_findings: list[ResearchFinding] = []

    # Risk
    risk_flags: list[RiskFlag] = []
    counterparty_note: str = ""

    # Scheduling
    next_check_at: str | None = None
    next_check_reason: str = ""

    # Display
    summary: str = ""
    one_line_verdict: str = ""

    # --- Discovery mode fields ---
    recommended_market_id: str | None = None
    recommended_market_title: str | None = None
    direction: Literal["YES", "NO"] | None = None
    entry_price: float | None = None
    position_size_usd: float | None = None
    event_overview: str | None = None
    friction_vs_edge: FrictionEdge | None = None
    recheck_conditions: list[str] = []
    crypto: CryptoContext | None = None

    # --- Position management fields ---
    thesis_status: ThesisStatus | None = None
    thesis_note: str | None = None
    current_pnl_note: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    alternative_market_id: str | None = None
    alternative_note: str | None = None

    # --- Internal dev feedback (not shown to users) ---
    dev_feedback: str | None = None

    model_config = ConfigDict(extra="ignore")

    def semantic_errors(self) -> list[str]:
        """Return list of semantic issues. Empty = OK."""
        errors = []

        if self.mode == "discovery":
            if self.action in ("BUY_YES", "BUY_NO"):
                if not self.why or len(self.why.strip()) < 10:
                    errors.append("BUY requires substantive why")
                if not self.supporting_findings:
                    errors.append("BUY requires at least 1 supporting_finding")
                if not self.recommended_market_id:
                    errors.append("BUY requires recommended_market_id")
                if not self.invalidation_findings:
                    errors.append("BUY requires invalidation_findings")
            elif self.action in ("WATCH", "PASS"):
                if not self.why_not or len((self.why_not or "").strip()) < 10:
                    errors.append("WATCH/PASS requires substantive why_not")
                if self.action == "PASS" and self.recommended_market_id:
                    errors.append("PASS must not have recommended_market_id")
                if self.action == "PASS" and self.entry_price is not None:
                    errors.append("PASS must not have entry_price")
        else:  # position_management
            if self.action in ("SELL_YES", "SELL_NO"):
                if not self.why or len(self.why.strip()) < 10:
                    errors.append("SELL requires substantive why")
                if self.thesis_status != "broken":
                    errors.append("SELL should have thesis_status=broken")
                if not self.invalidation_findings:
                    errors.append("SELL requires invalidation_findings")
            elif self.action == "HOLD":
                if not self.why or len(self.why.strip()) < 10:
                    errors.append("HOLD requires substantive why")
            elif self.action in ("REDUCE_YES", "REDUCE_NO"):
                if not self.why or len(self.why.strip()) < 10:
                    errors.append("REDUCE requires substantive why")
            if self.thesis_status is None:
                errors.append("position mode requires thesis_status")

        if not self.next_check_at:
            errors.append("next_check_at is required")
        if not self.summary or len(self.summary.strip()) < 5:
            errors.append("summary required")
        if not self.one_line_verdict or len(self.one_line_verdict.strip()) < 5:
            errors.append("one_line_verdict required")
        return errors
