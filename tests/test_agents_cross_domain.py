"""Tests for CrossDomainInsight agent."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.cross_domain import CrossDomainAgent, cross_domain_fallback
from scanner.agents.schemas import CrossDomainOutput
from scanner.calendar_events import CalendarEvent
from scanner.config import AgentConfig
from tests.conftest import make_cli_response, make_market

SAMPLE_CROSS_OUTPUT = {
    "market_id": "m1",
    "event_name": "CPI Release",
    "cross_domain_link": "Hot CPI → risk-off → BTC likely drops → threshold market reprices down.",
    "impact_direction": "negative_for_yes",
    "confidence": "medium",
    "research_note": "Consider the cross-domain impact before trading both markets.",
}


class TestCrossDomainAgent:
    @pytest.mark.asyncio
    async def test_analyze_cross_domain(self):
        agent = CrossDomainAgent(AgentConfig(model="sonnet"))
        market = make_market(market_type="crypto_threshold", title="BTC above 88K?")
        event = CalendarEvent(
            date="2026-03-29", type="economic_data", name="CPI Release",
            impact="high", keywords=["cpi"],
        )

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (make_cli_response(SAMPLE_CROSS_OUTPUT), b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.analyze(market, event)
            assert isinstance(result, CrossDomainOutput)
            assert result.impact_direction == "negative_for_yes"

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        agent = CrossDomainAgent(AgentConfig(model="sonnet"))
        market = make_market(market_type="crypto_threshold")
        event = CalendarEvent(date="2026-03-29", type="economic_data", name="CPI", impact="high", keywords=["cpi"])

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.analyze(market, event)
            assert isinstance(result, CrossDomainOutput)


class TestCrossDomainFallback:
    def test_fallback_with_known_link(self):
        market = make_market(market_type="crypto_threshold", market_id="m1")
        event = CalendarEvent(date="2026-03-29", type="economic_data", name="CPI", impact="high", keywords=["cpi"])
        result = cross_domain_fallback(market, event)
        assert isinstance(result, CrossDomainOutput)
        assert "crypto" in result.cross_domain_link.lower() or "macro" in result.cross_domain_link.lower()

    def test_fallback_unknown_link(self):
        market = make_market(market_type="sports", market_id="m2")
        event = CalendarEvent(date="2026-03-29", type="tech", name="WWDC", impact="medium", keywords=["apple"])
        result = cross_domain_fallback(market, event)
        assert result.confidence == "low"
