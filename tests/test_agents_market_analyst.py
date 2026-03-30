"""Tests for MarketAnalyst agent: objectivity, catalyst, resolution risk analysis."""

from unittest.mock import AsyncMock, patch

import pytest

from scanner.agents.market_analyst import MarketAnalystAgent, market_analyst_fallback
from scanner.agents.schemas import MarketAnalystOutput
from scanner.config import AgentConfig, HeuristicsConfig
from tests.conftest import make_cli_response, make_market

SAMPLE_AGENT_OUTPUT = {
    "market_id": "0xtest",
    "objectivity_score": 85,
    "objectivity_reasoning": "Clear binary outcome with named data source",
    "has_catalyst": True,
    "catalyst_description": "CPI release March 29 8:30AM ET",
    "catalyst_type": "economic_data_release",
    "market_type": "economic_data",
    "market_type_confidence": "high",
    "resolution_source": "Bureau of Labor Statistics",
    "resolution_clarity": "clear",
    "resolution_edge_cases": [],
    "resolution_risk": "low",
    "is_noise_market": False,
    "flags": [],
}


class TestMarketAnalystOutputSchema:
    def test_schema_validates_complete_output(self):
        output = MarketAnalystOutput.model_validate(SAMPLE_AGENT_OUTPUT)
        assert output.objectivity_score == 85
        assert output.market_type == "economic_data"
        assert output.resolution_risk == "low"

    def test_schema_generates_json_schema(self):
        schema = MarketAnalystOutput.model_json_schema()
        assert "properties" in schema
        assert "objectivity_score" in schema["properties"]
        assert "resolution_risk" in schema["properties"]


class TestMarketAnalystAgent:
    @pytest.mark.asyncio
    async def test_analyze_single_market(self):
        agent = MarketAnalystAgent(AgentConfig(model="haiku"))
        market = make_market(title="Will CPI exceed 3.5% in March?")

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response(SAMPLE_AGENT_OUTPUT), b""
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.analyze(market)
            assert isinstance(result, MarketAnalystOutput)
            assert result.objectivity_score == 85

    @pytest.mark.asyncio
    async def test_analyze_batch(self):
        agent = MarketAnalystAgent(AgentConfig(model="haiku"))
        markets = [
            make_market(market_id="m1", title="BTC above 88K?"),
            make_market(market_id="m2", title="CPI exceed 3.5%?"),
        ]

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = AsyncMock()
            output = {**SAMPLE_AGENT_OUTPUT, "market_id": f"m{call_count}"}
            proc.communicate.return_value = (make_cli_response(output), b"")
            proc.returncode = 0
            return proc

        with patch("scanner.agents.base.asyncio.create_subprocess_exec", side_effect=mock_exec):
            results = await agent.analyze_batch(markets)

        assert len(results) == 2
        assert all(isinstance(r, MarketAnalystOutput) for r in results)

    @pytest.mark.asyncio
    async def test_fallback_on_failure(self):
        agent = MarketAnalystAgent(AgentConfig(model="haiku"))
        market = make_market(title="BTC above 88K?")

        with patch("scanner.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.analyze(market)
            # Should return fallback result, not crash
            assert isinstance(result, MarketAnalystOutput)
            assert result.resolution_risk in ("low", "medium", "high")


class TestMarketAnalystFallback:
    def test_fallback_returns_valid_output(self):
        market = make_market(
            title="Will BTC be above $88,000 on March 30?",
            rules="Resolves based on CoinGecko BTC/USD price at 00:00 UTC.",
            resolution_source="https://coingecko.com",
        )
        heuristics = HeuristicsConfig(
            objective_blacklist_keywords=["best", "favorite", "strongest"],
            objective_whitelist_keywords=["will", "above", "below"],
        )
        result = market_analyst_fallback(market, heuristics)
        assert isinstance(result, MarketAnalystOutput)
        assert 0 <= result.objectivity_score <= 100
        assert result.market_id == market.market_id

    def test_fallback_detects_subjective_market(self):
        market = make_market(title="Which is the best AI model?")
        heuristics = HeuristicsConfig(
            objective_blacklist_keywords=["best", "favorite"],
            objective_whitelist_keywords=["will", "above"],
        )
        result = market_analyst_fallback(market, heuristics)
        assert result.objectivity_score < 50

    def test_fallback_detects_catalyst_keywords(self):
        market = make_market(title="Will CPI report exceed 3.5% before April?")
        heuristics = HeuristicsConfig()
        result = market_analyst_fallback(market, heuristics)
        assert result.has_catalyst is True

    def test_fallback_detects_resolution_source(self):
        market = make_market(
            resolution_source="https://coingecko.com",
            rules="Resolved based on CoinGecko price.",
        )
        heuristics = HeuristicsConfig(
            resolution_source_bonus_keywords=["coingecko", "associated press"],
        )
        result = market_analyst_fallback(market, heuristics)
        assert result.resolution_source == "https://coingecko.com"
        assert result.resolution_clarity in ("clear", "mostly_clear")
