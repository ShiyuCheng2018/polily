"""CrossDomainInsight Agent: analyze cross-domain impact between events and markets."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import CrossDomainOutput
from scanner.calendar_events import CROSS_DOMAIN_LINKS, CalendarEvent
from scanner.config import AgentConfig
from scanner.models import Market

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "cross_domain.txt"
if PROMPT_FILE.exists():
    SYSTEM_PROMPT = PROMPT_FILE.read_text()
else:
    logger.warning("Prompt file not found: %s", PROMPT_FILE)
    SYSTEM_PROMPT = "You are a cross-domain market analyst for Polymarket."


class CrossDomainAgent:
    """Agent 4: Analyze cross-domain impact between calendar events and markets."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=CrossDomainOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            fallback_fn=lambda prompt: CrossDomainOutput(
                market_id="unknown", event_name="unknown",
                cross_domain_link="AI agent offline.",
                impact_direction="uncertain", confidence="low",
                research_note="Manual cross-domain analysis required.",
            ).model_dump(),
        )

    async def analyze(self, market: Market, event: CalendarEvent) -> CrossDomainOutput:
        prompt = self._build_prompt(market, event)
        raw = await self._agent.invoke(prompt)
        try:
            return CrossDomainOutput.model_validate(raw)
        except Exception:
            logger.warning("Failed to validate cross-domain output, using fallback")
            return cross_domain_fallback(market, event)

    def _build_prompt(self, market: Market, event: CalendarEvent) -> str:
        data = {
            "market_id": market.market_id,
            "market_title": market.title,
            "market_type": market.market_type,
            "yes_price": market.yes_price,
            "days_to_resolution": market.days_to_resolution,
            "event_name": event.name,
            "event_type": event.type,
            "event_date": event.date,
            "event_impact": event.impact,
        }
        return f"Analyze cross-domain impact:\n{json.dumps(data, default=str)}"


def cross_domain_fallback(market: Market, event: CalendarEvent) -> CrossDomainOutput:
    """Rule-based fallback using static CROSS_DOMAIN_LINKS mapping."""
    key = (event.type, market.market_type or "other")
    link_text = CROSS_DOMAIN_LINKS.get(key)

    if link_text:
        return CrossDomainOutput(
            market_id=market.market_id,
            event_name=event.name,
            cross_domain_link=link_text,
            impact_direction="uncertain",
            confidence="medium",
            research_note=f"Consider {event.name}'s impact on {market.market_type} markets.",
        )

    return CrossDomainOutput(
        market_id=market.market_id,
        event_name=event.name,
        cross_domain_link=f"{event.type} event may affect {market.market_type} market — review manually.",
        impact_direction="uncertain",
        confidence="low",
        research_note="No known cross-domain pattern. Manual analysis recommended.",
    )
