"""NarrativeWriter Agent: generate analysis narratives for scored candidates."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import NarrativeWriterOutput
from scanner.config import AgentConfig
from scanner.reporting import ScoredCandidate

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "narrative_writer.txt"
if PROMPT_FILE.exists():
    SYSTEM_PROMPT = PROMPT_FILE.read_text()
else:
    logger.warning("Prompt file not found: %s — using minimal fallback prompt", PROMPT_FILE)
    SYSTEM_PROMPT = "You are a Polymarket trading analyst."


class NarrativeWriterAgent:
    """Agent 2: Generate natural-language narratives for scored candidates."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=NarrativeWriterOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            fallback_fn=lambda prompt: self._fallback_from_prompt(prompt),
        )

    async def generate(self, candidate: ScoredCandidate, context: str | None = None) -> NarrativeWriterOutput:
        """Generate narrative for a single candidate, optionally with previous analysis context."""
        prompt = self._build_prompt(candidate)
        if context:
            prompt += f"\n\n{context}"
        raw = await self._agent.invoke(prompt)
        try:
            return NarrativeWriterOutput.model_validate(raw)
        except Exception:
            logger.warning("Failed to validate narrative for %s, using fallback", candidate.market.market_id)
            return narrative_fallback(candidate)

    async def generate_batch(
        self, candidates: list[ScoredCandidate],
        max_concurrent: int | None = None,
        contexts: dict[str, str] | None = None,
    ) -> list[NarrativeWriterOutput]:
        """Generate narratives for multiple candidates in parallel.

        Args:
            contexts: optional {market_id: context_str} — per-candidate
                      previous analysis context appended to each prompt.
        """
        concurrency = max_concurrent or self.config.max_concurrent
        prompts = []
        for c in candidates:
            prompt = self._build_prompt(c)
            if contexts:
                ctx = contexts.get(c.market.market_id)
                if ctx:
                    prompt += f"\n\n{ctx}"
            prompts.append(prompt)
        raw_results = await self._agent.invoke_batch(prompts, max_concurrent=concurrency)

        outputs = []
        for i, raw in enumerate(raw_results):
            try:
                outputs.append(NarrativeWriterOutput.model_validate(raw))
            except Exception:
                outputs.append(narrative_fallback(candidates[i]))
        return outputs

    def _build_prompt(self, candidate: ScoredCandidate) -> str:
        m = candidate.market
        s = candidate.score
        mp = candidate.mispricing
        data = {
            "market_id": m.market_id,
            "title": m.title,
            "description": m.description,
            "market_type": m.market_type,
            "yes_price": m.yes_price,
            "no_price": m.no_price,
            "spread_pct_yes": m.spread_pct_yes,
            "round_trip_friction_pct": m.round_trip_friction_pct,
            "volume": m.volume,
            "days_to_resolution": m.days_to_resolution,
            "total_bid_depth_usd": m.total_bid_depth_usd,
            "total_ask_depth_usd": m.total_ask_depth_usd,
            "resolution_source": m.resolution_source,
            "structure_score": s.total,
            "score_breakdown": {
                "time": s.time_to_resolution,
                "objectivity": s.objectivity,
                "probability": s.probability_zone,
                "liquidity": s.liquidity_depth,
                "exitability": s.exitability,
                "catalyst": s.catalyst_proxy,
                "small_account": s.small_account_friendliness,
            },
            "mispricing_signal": mp.signal,
            "mispricing_details": mp.details,
            "theoretical_fair_value": mp.theoretical_fair_value,
        }
        return f"Generate analysis for this candidate:\n{json.dumps(data, default=str)}"

    def _fallback_from_prompt(self, prompt: str) -> dict:
        from scanner.utils import extract_market_id_from_prompt
        market_id = extract_market_id_from_prompt(prompt)
        return NarrativeWriterOutput(
            market_id=market_id,
            summary="AI 分析不可用，请手动查看市场详情。",
            why_it_passed=["通过了筛选器"],
            risk_flags=["AI 叙事不可用 — 需要手动审查"],
            counterparty_note="未知 — AI 离线",
            research_checklist=["直接在 Polymarket 上查看市场"],
            suggested_style="watch_only",
            one_line_verdict="AI 离线，请手动评估。",
        ).model_dump()


def narrative_fallback(candidate: ScoredCandidate) -> NarrativeWriterOutput:
    """Template-based fallback when AI agent is unavailable."""
    m = candidate.market
    s = candidate.score
    mp = candidate.mispricing

    # Build why_it_passed
    why = []
    if m.is_binary:
        why.append("Binary market with two clear outcomes")
    if m.days_to_resolution and m.days_to_resolution <= 7:
        why.append(f"Resolution within {m.days_to_resolution:.1f} days")
    if m.yes_price and 0.30 <= m.yes_price <= 0.70:
        why.append("Probability in preferred mid-range")
    if m.spread_pct_yes and m.spread_pct_yes < 0.04:
        why.append(f"Spread acceptable ({m.spread_pct_yes:.1%})")
    if not why:
        why.append("Passed all hard filters")

    # Build risk flags
    risks = []
    friction = m.round_trip_friction_pct
    if friction:
        risks.append(f"Round-trip friction ~{friction:.1%} eats into any edge")
    if mp.signal == "none":
        risks.append("No mispricing detected — market may be efficiently priced")
    if m.total_bid_depth_usd and m.total_bid_depth_usd < 1000:
        risks.append(f"Thin bid depth (${m.total_bid_depth_usd:.0f}) — exit may be difficult")
    if not risks:
        risks.append("Review resolution rules carefully")

    # Determine style
    if mp.signal in ("moderate", "strong"):
        style = "research_candidate"
    elif mp.signal == "weak":
        style = "research_repricing"
    else:
        style = "watch_only"

    # Summary
    parts = [f"{'Binary' if m.is_binary else 'Multi-outcome'} {m.market_type or 'market'}"]
    if m.days_to_resolution:
        parts.append(f"{m.days_to_resolution:.1f}d to resolution")
    if mp.signal != "none":
        parts.append(f"{mp.signal} mispricing signal")
    summary = f"{', '.join(parts)}. Score {s.total:.0f}/100."

    return NarrativeWriterOutput(
        market_id=m.market_id,
        summary=summary,
        why_it_passed=why,
        risk_flags=risks,
        counterparty_note=f"Market type '{m.market_type}' — review counterparty quality manually.",
        research_checklist=[
            "Read resolution rules on Polymarket",
            "Check recent price movement (24h)",
            "Verify resolution source is reputable",
            "Ask: what do I know that the market doesn't?",
            "Check order book depth before placing order",
        ],
        suggested_style=style,
        one_line_verdict=summary,
    )
