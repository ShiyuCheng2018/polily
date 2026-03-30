"""Tests for BriefingAnalyst agent."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.briefing_analyst import BriefingAnalystAgent, briefing_fallback
from scanner.agents.schemas import BriefingOutput
from scanner.config import AgentConfig
from scanner.daily_briefing import DailyBriefing, MarketDelta
from tests.conftest import make_cli_response

SAMPLE_BRIEFING_OUTPUT = {
    "market_narrative": "BTC broke above 87K overnight, crypto threshold markets repriced upward.",
    "tracking_insights": ["BTC 88K market moved +14%", "CPI market stable ahead of release"],
    "paper_trade_observations": "1 open position, unrealized +$2.40",
    "upcoming_focus": "CPI release tomorrow — macro markets will reprice instantly.",
    "action_summary": "Focus on CPI cross-domain impact on crypto positions.",
}


class TestBriefingAnalystAgent:
    @pytest.mark.asyncio
    async def test_analyze_briefing(self):
        agent = BriefingAnalystAgent(AgentConfig(model="sonnet"))
        briefing = DailyBriefing(
            deltas=[MarketDelta(
                market_id="m1", title="BTC above 88K?",
                yesterday_price=0.42, today_price=0.48,
                price_change_pct=0.143, yesterday_score=82, today_score=80,
                yesterday_mispricing="moderate", today_mispricing="weak",
            )],
            new_markets=[],
            summary="1 tracked, 0 new",
        )

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (make_cli_response(SAMPLE_BRIEFING_OUTPUT), b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.analyze(briefing)
            assert isinstance(result, BriefingOutput)
            assert "BTC" in result.market_narrative

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        agent = BriefingAnalystAgent(AgentConfig(model="sonnet"))
        briefing = DailyBriefing(deltas=[], new_markets=[], summary="test")

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.analyze(briefing)
            assert isinstance(result, BriefingOutput)


class TestBriefingFallback:
    def test_fallback_returns_valid_output(self):
        briefing = DailyBriefing(
            deltas=[MarketDelta(
                market_id="m1", title="Test", yesterday_price=0.50,
                today_price=0.55, price_change_pct=0.10,
                yesterday_score=80, today_score=82,
                yesterday_mispricing="none", today_mispricing="none",
            )],
            new_markets=[{"title": "New market"}],
            summary="1 tracked, 1 new",
        )
        result = briefing_fallback(briefing)
        assert isinstance(result, BriefingOutput)
        assert len(result.tracking_insights) > 0
