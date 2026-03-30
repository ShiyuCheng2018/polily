"""Tests for ReviewAnalyst agent."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.review_analyst import ReviewAnalystAgent, review_fallback
from scanner.agents.schemas import ReviewOutput
from scanner.config import AgentConfig
from tests.conftest import make_cli_response

SAMPLE_REVIEW_OUTPUT = {
    "behavior_analysis": "You trade crypto markets most frequently (7/12 trades). Win rate highest in crypto (71%).",
    "category_insights": ["Crypto: 71% win rate, strongest edge", "Macro: 33% win rate, consider reducing"],
    "calibration_feedback": "At price 0.40-0.60, your YES picks resolved correctly 62% of the time.",
    "recommendations": ["Focus on crypto threshold markets", "Reduce macro market exposure", "Wait for mispricing > 8%"],
}


class TestReviewAnalystAgent:
    @pytest.mark.asyncio
    async def test_analyze_review(self):
        agent = ReviewAnalystAgent(AgentConfig(model="sonnet"))
        stats = {
            "total_trades": 12, "resolved": 10, "wins": 6, "losses": 4,
            "win_rate": 0.6, "total_paper_pnl": 15.20,
            "total_friction_adjusted_pnl": 7.40, "open": 2,
        }

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (make_cli_response(SAMPLE_REVIEW_OUTPUT), b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.analyze(stats)
            assert isinstance(result, ReviewOutput)
            assert "crypto" in result.behavior_analysis.lower()

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        agent = ReviewAnalystAgent(AgentConfig(model="sonnet"))

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.analyze({"total_trades": 5, "resolved": 3})
            assert isinstance(result, ReviewOutput)


class TestReviewFallback:
    def test_fallback_valid_output(self):
        stats = {"total_trades": 10, "resolved": 8, "wins": 5, "losses": 3,
                 "win_rate": 0.625, "total_paper_pnl": 12.0,
                 "total_friction_adjusted_pnl": 5.0, "open": 2}
        result = review_fallback(stats)
        assert isinstance(result, ReviewOutput)
        assert len(result.recommendations) > 0

    def test_fallback_no_trades(self):
        stats = {"total_trades": 0, "resolved": 0, "wins": 0, "losses": 0,
                 "win_rate": 0, "total_paper_pnl": 0, "total_friction_adjusted_pnl": 0, "open": 0}
        result = review_fallback(stats)
        assert "more trades" in result.behavior_analysis.lower() or "not enough" in result.behavior_analysis.lower()
