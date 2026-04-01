"""Tests for NarrativeWriter agent."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.narrative_writer import NarrativeWriterAgent, narrative_fallback
from scanner.agents.schemas import NarrativeWriterOutput
from scanner.config import AgentConfig
from scanner.mispricing import MispricingResult
from scanner.reporting import ScoredCandidate
from scanner.scoring import ScoreBreakdown
from tests.conftest import make_cli_response, make_market

SAMPLE_NARRATIVE_OUTPUT = {
    "market_id": "0xtest",
    "action": "WATCH",
    "bias": "YES",
    "strength": "medium",
    "confidence": "medium",
    "opportunity_type": "slow_structure",
    "time_window": {"urgency": "normal", "note": "还剩 2.0 天"},
    "why_now": "",
    "why_not_now": "摩擦吃掉 60% 潜在利润",
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
    "suggested_style": "research_candidate",
    "one_line_verdict": "Moderate mispricing in crypto threshold, thin edge after friction.",
}


def _make_scored_candidate(**overrides) -> ScoredCandidate:
    return ScoredCandidate(
        market=make_market(**{k: v for k, v in overrides.items() if k in ("market_id", "title", "market_type", "yes_price")}),
        score=ScoreBreakdown(
            time_to_resolution=12, objectivity=16, probability_zone=16,
            liquidity_depth=18, exitability=7, catalyst_proxy=3,
            small_account_friendliness=8, total=80,
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
                make_cli_response(SAMPLE_NARRATIVE_OUTPUT), b""
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


class TestNarrativeWriterBatchWithContext:
    @pytest.mark.asyncio
    async def test_batch_with_per_candidate_context(self):
        """generate_batch passes per-candidate context into prompts."""
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        c1 = _make_scored_candidate(market_id="m1")
        c2 = _make_scored_candidate(market_id="m2")

        out1 = {**SAMPLE_NARRATIVE_OUTPUT, "market_id": "m1"}
        out2 = {**SAMPLE_NARRATIVE_OUTPUT, "market_id": "m2"}

        captured_prompts = []

        async def mock_invoke(prompt, **kwargs):
            captured_prompts.append(prompt)
            # Return based on which market
            if "m1" in prompt:
                return out1
            return out2

        with patch.object(agent._agent, "invoke", side_effect=mock_invoke):
            with patch.object(agent._agent, "invoke_batch") as mock_batch:
                # Make invoke_batch call invoke for each prompt
                async def batch_impl(prompts, **kw):
                    return [await mock_invoke(p) for p in prompts]
                mock_batch.side_effect = batch_impl

                contexts = {
                    "m1": "上次分析: BTC价格可能上涨",
                    # m2 has no context
                }
                results = await agent.generate_batch([c1, c2], contexts=contexts)

                assert len(results) == 2
                # m1's prompt should contain context
                m1_prompt = [p for p in captured_prompts if "m1" in p][0]
                assert "上次分析" in m1_prompt
                # m2's prompt should NOT contain m1's context
                m2_prompt = [p for p in captured_prompts if "m2" in p][0]
                assert "上次分析" not in m2_prompt

    @pytest.mark.asyncio
    async def test_batch_without_context_unchanged(self):
        """generate_batch without contexts works as before."""
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        c1 = _make_scored_candidate(market_id="m1")

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response({**SAMPLE_NARRATIVE_OUTPUT, "market_id": "m1"}), b""
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            results = await agent.generate_batch([c1])
            assert len(results) == 1
            assert results[0].market_id == "m1"


class TestNarrativeFallback:
    def test_fallback_returns_valid_output(self):
        candidate = _make_scored_candidate()
        result = narrative_fallback(candidate)
        assert isinstance(result, NarrativeWriterOutput)
        assert result.market_id == "0xtest"
        assert len(result.summary) > 0
        assert result.action in ("BUY_YES", "BUY_NO", "WATCH", "PASS")
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
