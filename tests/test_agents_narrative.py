"""Tests for NarrativeWriter agent."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.narrative_writer import NarrativeWriterAgent, narrative_fallback
from scanner.agents.schemas import NarrativeWriterOutput
from scanner.core.config import AgentConfig
from tests.conftest import make_cli_response_structured

SAMPLE_NARRATIVE_OUTPUT = {
    "event_id": "ev_test",
    "confidence": "medium",
    "time_window": {"urgency": "normal", "note": "还剩 2.0 天"},
    "operations": [
        {
            "action": "BUY_YES",
            "market_id": "0xtest",
            "market_title": "BTC > $88K",
            "entry_price": 0.62,
            "position_size_usd": 20,
            "reasoning": "Moderate mispricing with edge after friction",
        },
    ],
    "operations_commentary": "单一方向操作，仓位适中",
    "analysis": "BTC approaching threshold with momentum",
    "analysis_commentary": "技术面支撑，基本面中性",
    "summary": "Crypto market with moderate mispricing signal, edge after friction.",
    "risk_flags": [
        {"text": "Round-trip friction eats most edge", "severity": "critical"},
        {"text": "Bots dominate this market", "severity": "warning"},
    ],
    "risk_commentary": "摩擦是主要风险",
    "supporting_findings": [
        {"finding": "BTC 当前价格 $67,750", "source": "Binance", "impact": "距阈值 $88k 还有 23%"},
    ],
    "invalidation_findings": [
        {"finding": "若 BTC 突破 $70K", "source": "技术面", "impact": "YES 可能低估"},
    ],
    "evidence_commentary": "证据支持方向但不确定",
    "next_check_at": "2026-04-12T12:00:00",
    "next_check_reason": "Monitor friction levels",
}


class TestNarrativeWriterAgent:
    @pytest.mark.asyncio
    async def test_generate_narrative(self):
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response_structured(SAMPLE_NARRATIVE_OUTPUT), b""
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.generate(event_id="ev_test")
            assert isinstance(result, NarrativeWriterOutput)
            assert result.event_id == "ev_test"
            assert len(result.operations) == 1
            assert result.operations[0].action == "BUY_YES"
            assert len(result.risk_flags) > 0
            assert len(result.supporting_findings) > 0

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.generate(event_id="ev_test")
            assert isinstance(result, NarrativeWriterOutput)
            assert len(result.summary) > 0


class TestNarrativeFallback:
    def test_fallback_returns_valid_output(self):
        result = narrative_fallback("ev_test")
        assert isinstance(result, NarrativeWriterOutput)
        assert result.event_id == "ev_test"
        assert len(result.summary) > 0
        assert result.confidence == "low"

    def test_fallback_has_risk_flags_with_severity(self):
        result = narrative_fallback("ev_test")
        assert len(result.risk_flags) > 0
        for rf in result.risk_flags:
            assert rf.severity in ("critical", "warning", "info")

    def test_fallback_operations_empty(self):
        """Fallback returns empty operations since AI was unavailable."""
        result = narrative_fallback("ev_test")
        assert result.operations == []

    def test_fallback_has_next_check(self):
        result = narrative_fallback("ev_test")
        assert result.next_check_at is not None
        assert result.next_check_reason != ""
