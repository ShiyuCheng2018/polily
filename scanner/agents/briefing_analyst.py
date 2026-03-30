"""BriefingAnalyst Agent: interpret daily market deltas with AI."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import BriefingOutput
from scanner.config import AgentConfig
from scanner.daily_briefing import DailyBriefing

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "briefing_analyst.txt"
if PROMPT_FILE.exists():
    SYSTEM_PROMPT = PROMPT_FILE.read_text()
else:
    logger.warning("Prompt file not found: %s", PROMPT_FILE)
    SYSTEM_PROMPT = "You are a Polymarket daily briefing analyst."


class BriefingAnalystAgent:
    """Agent 3: Interpret daily deltas with natural language insights."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=BriefingOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            fallback_fn=lambda prompt: briefing_fallback(
                DailyBriefing(deltas=[], new_markets=[], summary="AI offline")
            ).model_dump(),
        )

    async def analyze(self, briefing: DailyBriefing) -> BriefingOutput:
        prompt = self._build_prompt(briefing)
        raw = await self._agent.invoke(prompt)
        try:
            return BriefingOutput.model_validate(raw)
        except Exception:
            logger.warning("Failed to validate briefing output, using fallback")
            return briefing_fallback(briefing)

    def _build_prompt(self, briefing: DailyBriefing) -> str:
        deltas_data = []
        for d in briefing.deltas:
            deltas_data.append({
                "title": d.title,
                "yesterday_price": d.yesterday_price,
                "today_price": d.today_price,
                "price_change_pct": d.price_change_pct,
                "disappeared": d.disappeared,
            })
        data = {
            "summary": briefing.summary,
            "deltas": deltas_data,
            "new_markets_count": len(briefing.new_markets),
        }
        return f"Generate daily briefing:\n{json.dumps(data, default=str)}"


def briefing_fallback(briefing: DailyBriefing) -> BriefingOutput:
    """Rule-based fallback for daily briefing."""
    insights = []
    for d in briefing.deltas:
        if d.disappeared:
            insights.append(f"{d.title[:40]} — resolved/removed")
        elif d.price_change_pct and abs(d.price_change_pct) > 0.05:
            direction = "up" if d.price_change_pct > 0 else "down"
            insights.append(f"{d.title[:40]} — {direction} {abs(d.price_change_pct):.0%}")
        else:
            insights.append(f"{d.title[:40]} — stable")

    return BriefingOutput(
        market_narrative=briefing.summary,
        tracking_insights=insights if insights else ["No tracked markets"],
        paper_trade_observations=None,
        upcoming_focus="Check event calendar for upcoming catalysts.",
        action_summary="Review today's scan results.",
    )
