"""MarketAnalyst Agent: semantic analysis of market objectivity, catalyst, resolution risk."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import MarketAnalystOutput
from scanner.config import AgentConfig, HeuristicsConfig
from scanner.models import Market

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "market_analyst.txt"
if PROMPT_FILE.exists():
    SYSTEM_PROMPT = PROMPT_FILE.read_text()
else:
    logger.warning("Prompt file not found: %s — using minimal fallback prompt", PROMPT_FILE)
    SYSTEM_PROMPT = "You are a Polymarket market analyst."

# Catalyst-indicating keywords for fallback heuristic
CATALYST_KEYWORDS = [
    "before", "deadline", "vote", "release", "announcement",
    "report", "election", "earnings", "launch", "decision",
]


class MarketAnalystAgent:
    """Agent 1: Analyze markets for objectivity, catalyst, resolution risk.

    Uses claude CLI (Haiku) for semantic analysis.
    Falls back to keyword heuristics if CLI fails.
    """

    def __init__(self, config: AgentConfig, heuristics: HeuristicsConfig | None = None):
        self.config = config
        self.heuristics = heuristics or HeuristicsConfig()
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=MarketAnalystOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            fallback_fn=lambda prompt: self._fallback_from_prompt(prompt),
        )

    async def analyze(self, market: Market) -> MarketAnalystOutput:
        """Analyze a single market. Returns structured output or fallback."""
        prompt = self._build_prompt(market)
        raw = await self._agent.invoke(prompt)
        try:
            return MarketAnalystOutput.model_validate(raw)
        except Exception:
            logger.warning("Failed to validate agent output for %s, using fallback", market.market_id)
            return market_analyst_fallback(market, self.heuristics)

    async def analyze_batch(
        self, markets: list[Market], max_concurrent: int | None = None,
    ) -> list[MarketAnalystOutput]:
        """Analyze multiple markets in parallel."""
        concurrency = max_concurrent or self.config.max_concurrent
        prompts = [self._build_prompt(m) for m in markets]
        raw_results = await self._agent.invoke_batch(prompts, max_concurrent=concurrency)

        outputs = []
        for i, raw in enumerate(raw_results):
            try:
                outputs.append(MarketAnalystOutput.model_validate(raw))
            except Exception:
                logger.warning("Fallback for market %s", markets[i].market_id)
                outputs.append(market_analyst_fallback(markets[i], self.heuristics))
        return outputs

    def _build_prompt(self, market: Market) -> str:
        data = {
            "market_id": market.market_id,
            "title": market.title,
            "description": market.description,
            "rules": market.rules,
            "outcomes": market.outcomes,
            "resolution_source": market.resolution_source,
            "category": market.category,
            "tags": market.tags,
            "yes_price": market.yes_price,
            "days_to_resolution": market.days_to_resolution,
        }
        return f"Analyze this market:\n{json.dumps(data, default=str)}"

    def _fallback_from_prompt(self, prompt: str) -> dict:
        """Produce a fallback dict from the prompt text (best-effort)."""
        from scanner.utils import extract_market_id_from_prompt
        market_id = extract_market_id_from_prompt(prompt)
        return MarketAnalystOutput(
            market_id=market_id,
            objectivity_score=50,
            objectivity_reasoning="Fallback: could not reach AI agent",
            has_catalyst=False,
            market_type="other",
            resolution_risk="medium",
        ).model_dump()


def market_analyst_fallback(
    market: Market,
    heuristics: HeuristicsConfig,
) -> MarketAnalystOutput:
    """Rule-based fallback when AI agent is unavailable.

    Uses keyword matching for objectivity, catalyst, and resolution risk.
    """
    title_lower = market.title.lower()
    rules_lower = (market.rules or "").lower()
    combined = f"{title_lower} {rules_lower}"

    # Objectivity scoring
    obj_score = 50  # baseline
    whitelist_hits = sum(1 for kw in heuristics.objective_whitelist_keywords if kw.lower() in title_lower)
    blacklist_hits = sum(1 for kw in heuristics.objective_blacklist_keywords if kw.lower() in title_lower)
    obj_score += whitelist_hits * 8
    obj_score -= blacklist_hits * 20
    if market.is_binary:
        obj_score += 10
    if market.resolution_source:
        obj_score += 10
        # Check resolution source quality
        for kw in heuristics.resolution_source_bonus_keywords:
            if kw.lower() in (market.resolution_source or "").lower():
                obj_score += 5
                break
    obj_score = max(0, min(100, obj_score))

    # Catalyst detection
    has_catalyst = any(kw in combined for kw in CATALYST_KEYWORDS)
    catalyst_desc = None
    catalyst_type = None
    if has_catalyst:
        for kw in CATALYST_KEYWORDS:
            if kw in combined:
                catalyst_desc = f"Title contains '{kw}'"
                catalyst_type = "other"
                break

    # Resolution clarity
    resolution_clarity = "unclear"
    if market.resolution_source:
        for kw in heuristics.resolution_source_bonus_keywords:
            if kw.lower() in (market.resolution_source or "").lower() + " " + rules_lower:
                resolution_clarity = "clear"
                break
        else:
            resolution_clarity = "mostly_clear"
    elif market.rules and len(market.rules) > 50:
        resolution_clarity = "mostly_clear"

    # Resolution risk
    resolution_risk = "medium"
    if resolution_clarity == "clear":
        resolution_risk = "low"
    elif resolution_clarity == "unclear":
        resolution_risk = "high"

    # Market type (reuse classifier logic inline for fallback)
    market_type = market.market_type or "other"

    return MarketAnalystOutput(
        market_id=market.market_id,
        objectivity_score=obj_score,
        objectivity_reasoning=f"Keyword-based: {whitelist_hits} objective, {blacklist_hits} subjective hits",
        has_catalyst=has_catalyst,
        catalyst_description=catalyst_desc,
        catalyst_type=catalyst_type,
        market_type=market_type,
        market_type_confidence="low",
        resolution_source=market.resolution_source,
        resolution_clarity=resolution_clarity,
        resolution_edge_cases=[],
        resolution_risk=resolution_risk,
        is_noise_market=False,
        flags=[],
    )
