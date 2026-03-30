"""ReviewAnalyst Agent: analyze paper trading patterns and provide coaching."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import ReviewOutput
from scanner.config import AgentConfig

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "review_analyst.txt"
if PROMPT_FILE.exists():
    SYSTEM_PROMPT = PROMPT_FILE.read_text()
else:
    logger.warning("Prompt file not found: %s", PROMPT_FILE)
    SYSTEM_PROMPT = "You are a trading performance coach."


class ReviewAnalystAgent:
    """Agent 5: Analyze paper trading behavior and provide coaching."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=ReviewOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            fallback_fn=lambda prompt: review_fallback({}).model_dump(),
        )

    async def analyze(self, stats: dict) -> ReviewOutput:
        prompt = f"Review this trader's performance:\n{json.dumps(stats, default=str)}"
        raw = await self._agent.invoke(prompt)
        try:
            return ReviewOutput.model_validate(raw)
        except Exception:
            logger.warning("Failed to validate review output, using fallback")
            return review_fallback(stats)


def review_fallback(stats: dict) -> ReviewOutput:
    """Rule-based fallback for performance review."""
    total = stats.get("total_trades", 0)
    resolved = stats.get("resolved", 0)
    win_rate = stats.get("win_rate", 0)
    pnl = stats.get("total_paper_pnl", 0)
    friction_pnl = stats.get("total_friction_adjusted_pnl", 0)

    if total < 10:
        return ReviewOutput(
            behavior_analysis=f"Not enough data ({total} trades). Need at least 10-20 resolved trades for meaningful analysis.",
            category_insights=["Accumulate more trades before drawing conclusions."],
            calibration_feedback="Sample too small for calibration analysis.",
            recommendations=[
                "Continue paper trading for at least 2 more weeks",
                "Try to reach 20+ resolved trades",
                "Focus on 1-2 market types you understand best",
            ],
        )

    recommendations = []
    if win_rate > 0.55:
        behavior = f"Win rate {win_rate:.0%} is above breakeven. {resolved} resolved trades."
    else:
        behavior = f"Win rate {win_rate:.0%} is near or below breakeven. Review your edge."
        recommendations.append("Re-evaluate your judgment criteria — are you trading on signal or impulse?")

    if friction_pnl < 0 < pnl:
        recommendations.append(f"Paper PnL ${pnl:+.2f} turns negative after friction (${friction_pnl:+.2f}). Focus on tighter-spread markets.")
    elif friction_pnl > 0:
        recommendations.append(f"Friction-adjusted PnL ${friction_pnl:+.2f} is positive — edge exists but may be thin.")

    recommendations.append("Track which market types produce your best results.")
    recommendations.append("Avoid trading when no mispricing signal is detected.")

    return ReviewOutput(
        behavior_analysis=behavior,
        category_insights=[f"Overall: {resolved} resolved, {win_rate:.0%} win rate, PnL ${pnl:+.2f}"],
        calibration_feedback=f"Win rate {win_rate:.0%} across {resolved} trades. Need category breakdown for deeper analysis.",
        recommendations=recommendations[:5],
    )
