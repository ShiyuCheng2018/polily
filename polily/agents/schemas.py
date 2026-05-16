"""Polily agent schemas.

v0.12.0+ uses :class:`AgentMarkdownOutput` for the new markdown-output
agent contract. The pre-v0.12.0 :class:`NarrativeWriterOutput` and its
sub-models are kept in :mod:`polily.agents.legacy_schemas` and
re-exported here so existing imports keep working without churn during
the v0.12.x cycle.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# Re-export legacy v0.11.x types for backward-compat imports.
# (Used by tests and the legacy_analysis_panel rendering path for
# narrative_format='json' rows.)
from polily.agents.legacy_schemas import (  # noqa: F401  -- public re-exports
    AnalysisMode,
    Confidence,
    CryptoContext,
    NarrativeWriterOutput,
    Operation,
    PositionAdvice,
    ResearchFinding,
    RiskFlag,
    StopLossOrTakeProfit,
    ThesisStatus,
    TimeWindow,
)

__all__ = [
    "AgentMarkdownOutput",
    # Legacy re-exports
    "AnalysisMode",
    "Confidence",
    "CryptoContext",
    "NarrativeWriterOutput",
    "Operation",
    "PositionAdvice",
    "ResearchFinding",
    "RiskFlag",
    "StopLossOrTakeProfit",
    "ThesisStatus",
    "TimeWindow",
]


class AgentMarkdownOutput(BaseModel):
    """v0.12.0 agent output — pure Markdown body + minimal metadata.

    Replaces v0.11.x NarrativeWriterOutput (17 fields). Field count drops to
    five because TUI renders ``markdown_body`` verbatim and only ``next_check_at``
    has programmatic consumption (daemon scheduler).
    """

    markdown_body: str
    next_check_at: str
    next_check_reason: str
    urgency: Literal["urgent", "normal", "no_rush"] = "normal"
    dev_feedback: str = ""

    model_config = ConfigDict(extra="ignore")

    def semantic_errors(self) -> list[str]:
        errors: list[str] = []
        if not self.markdown_body or len(self.markdown_body.strip()) < 10:
            errors.append("markdown_body too short (< 10 chars)")
        if not self.next_check_at:
            errors.append("next_check_at is required")
        return errors
