"""Pydantic models for AI agent input/output schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

# --- Shared types ---

AnalysisMode = Literal["discovery", "position_management"]
Confidence = Literal["low", "medium", "high"]

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


class Operation(BaseModel):
    """A single trading operation recommendation."""
    action: str  # BUY_YES, BUY_NO, SELL_YES, SELL_NO, REDUCE_YES, REDUCE_NO, HOLD
    market_id: str | None = None
    market_title: str | None = None
    entry_price: float | None = None
    position_size_usd: float | None = None
    reasoning: str = ""  # why this specific operation


# --- Main output schema ---

class NarrativeWriterOutput(BaseModel):
    """Unified AI analysis output — modular structure with agent commentary."""

    event_id: str
    mode: AnalysisMode = "discovery"
    confidence: Confidence = "low"

    # Modular content
    operations: list[Operation] = []  # trading operations (can be empty for WATCH/PASS)
    operations_commentary: str = ""   # agent's interpretation of operations

    analysis: str = ""                # event-level logic (macro, fundamentals, timing)
    analysis_commentary: str = ""     # agent's interpretation

    supporting_findings: list[ResearchFinding] = []
    invalidation_findings: list[ResearchFinding] = []
    evidence_commentary: str = ""     # agent's interpretation of evidence

    risk_flags: list[RiskFlag] = []
    risk_commentary: str = ""         # agent's interpretation of risks

    # Position mode
    thesis_status: ThesisStatus | None = None
    thesis_note: str | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    alternative_market_id: str | None = None
    alternative_note: str | None = None

    # Summary (final synthesis of ALL modules)
    summary: str = ""

    # Scheduling
    time_window: TimeWindow = TimeWindow(urgency="normal", note="")
    next_check_at: str | None = None
    next_check_reason: str = ""

    # Dev feedback
    dev_feedback: str | None = None

    model_config = ConfigDict(extra="ignore")

    def semantic_errors(self) -> list[str]:
        """Return list of semantic issues. Empty = OK."""
        errors = []

        # If operations list is not empty, each operation must have action and reasoning
        for i, op in enumerate(self.operations):
            if not op.action:
                errors.append(f"operation[{i}] missing action")
            if not op.reasoning:
                errors.append(f"operation[{i}] missing reasoning")

        # If mode is position_management, thesis_status is required
        if self.mode == "position_management":
            if self.thesis_status is None:
                errors.append("position mode requires thesis_status")

        # summary must be non-empty
        if not self.summary or len(self.summary.strip()) < 5:
            errors.append("summary required")

        # next_check_at is required
        if not self.next_check_at:
            errors.append("next_check_at is required")

        return errors
