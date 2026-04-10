"""Tests for NarrativeWriter agent."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.narrative_writer import NarrativeWriterAgent, narrative_fallback
from scanner.agents.schemas import NarrativeWriterOutput
from scanner.core.config import AgentConfig
from scanner.scan.mispricing import MispricingResult
from scanner.scan.reporting import ScoredCandidate
from scanner.scan.scoring import ScoreBreakdown
from tests.conftest import make_cli_response_structured, make_market

SAMPLE_NARRATIVE_OUTPUT = {
    "market_id": "0xtest",
    "action": "WATCH",
    "bias": "YES",
    "strength": "medium",
    "confidence": "medium",
    "opportunity_type": "slow_structure",
    "time_window": {"urgency": "normal", "note": "还剩 2.0 天"},
    "why_now": "",
    "why_not_now": "摩擦吃掉 60% 潜在利润，当前不值得进场",
    "friction_vs_edge": "roughly_equals",
    "execution_risk": "low",
    "summary": "Crypto market with moderate mispricing signal.",
    "risk_flags": [
        {"text": "Round-trip friction eats most edge", "severity": "critical"},
        {"text": "Bots dominate this market", "severity": "warning"},
    ],
    "counterparty_note": "Crypto threshold markets are bot-heavy.",
    "supporting_findings": [
        {"finding": "BTC 当前价格 $67,750", "source": "Binance", "impact": "距阈值 $88k 还有 23%"},
    ],
    "invalidation_findings": [
        {"finding": "若 BTC 突破 $70K", "source": "技术面", "impact": "YES 可能低估"},
    ],
    "watch": {"watch_reason": "摩擦太高", "better_entry": "YES<=0.50", "trigger_event": "BTC突破70K", "invalidation": "结算前不动"},
    "one_line_verdict": "Moderate mispricing in crypto threshold, thin edge after friction.",
}


def _make_scored_candidate(**overrides) -> ScoredCandidate:
    return ScoredCandidate(
        market=make_market(**{k: v for k, v in overrides.items() if k in ("market_id", "title", "market_type", "yes_price")}),
        score=ScoreBreakdown(
            liquidity_structure=20, objective_verifiability=18,
            probability_space=16, time_structure=12,
            trading_friction=8, total=74,
        ),
        mispricing=MispricingResult(
            signal="moderate", theoretical_fair_value=0.49,
            deviation_pct=0.06, details="Model 0.49, market 0.55",
        ),
    )


class TestNarrativeWriterAgent:
    @pytest.mark.asyncio
    async def test_generate_narrative(self):
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        candidate = _make_scored_candidate()

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response_structured(SAMPLE_NARRATIVE_OUTPUT), b""
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.generate(candidate)
            assert isinstance(result, NarrativeWriterOutput)
            assert result.action == "WATCH"
            assert len(result.risk_flags) > 0
            assert len(result.supporting_findings) > 0

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        candidate = _make_scored_candidate()

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.generate(candidate)
            assert isinstance(result, NarrativeWriterOutput)
            assert len(result.summary) > 0


class TestNarrativeFallback:
    def test_fallback_returns_valid_output(self):
        candidate = _make_scored_candidate()
        result = narrative_fallback(candidate)
        assert isinstance(result, NarrativeWriterOutput)
        assert result.market_id == "0xtest"
        assert len(result.summary) > 0
        assert result.action in ("BUY_YES", "BUY_NO", "WATCH", "PASS", "HOLD", "SELL", "REDUCE")
        assert result.confidence == "low"

    def test_fallback_has_risk_flags_with_severity(self):
        candidate = _make_scored_candidate()
        result = narrative_fallback(candidate)
        assert len(result.risk_flags) > 0
        for rf in result.risk_flags:
            assert rf.severity in ("critical", "warning", "info")

    def test_fallback_pass_when_no_mispricing(self):
        candidate = _make_scored_candidate()
        candidate.mispricing = MispricingResult(signal="none")
        result = narrative_fallback(candidate)
        assert result.action == "PASS"

    def test_fallback_has_time_window(self):
        candidate = _make_scored_candidate()
        result = narrative_fallback(candidate)
        assert result.time_window.urgency in ("urgent", "normal", "no_rush")

    def test_fallback_has_friction_vs_edge(self):
        candidate = _make_scored_candidate()
        result = narrative_fallback(candidate)
        assert result.friction_vs_edge in ("edge_exceeds", "roughly_equals", "friction_exceeds")
