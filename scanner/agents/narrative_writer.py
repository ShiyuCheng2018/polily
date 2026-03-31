"""NarrativeWriter Agent: generate analysis narratives for scored candidates."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import NarrativeWriterOutput, RiskFlag, TimeWindow
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

    async def generate(self, candidate: ScoredCandidate, context: str | None = None,
                       include_bias: bool = False) -> NarrativeWriterOutput:
        """Generate narrative for a single candidate, optionally with previous analysis context."""
        prompt = self._build_prompt(candidate, include_bias=include_bias)
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
        include_bias: bool = False,
    ) -> list[NarrativeWriterOutput]:
        """Generate narratives for multiple candidates in parallel.

        Args:
            contexts: optional {market_id: context_str} — per-candidate
                      previous analysis context appended to each prompt.
        """
        concurrency = max_concurrent or self.config.max_concurrent
        prompts = []
        for c in candidates:
            prompt = self._build_prompt(c, include_bias=include_bias)
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

    def _build_prompt(self, candidate: ScoredCandidate, include_bias: bool = False) -> str:
        m = candidate.market
        s = candidate.score
        mp = candidate.mispricing

        # Calculate friction vs edge for prompt context
        friction = m.round_trip_friction_pct or 0.04
        edge = mp.deviation_pct or 0
        friction_ratio = (friction / edge * 100) if edge > 0 else None

        data = {
            "market_id": m.market_id,
            "title": m.title,
            "description": m.description,
            "market_type": m.market_type,
            "tags": m.tags,
            "yes_price": m.yes_price,
            "no_price": m.no_price,
            "spread_pct_yes": m.spread_pct_yes,
            "round_trip_friction_pct": m.round_trip_friction_pct,
            "friction_vs_edge": f"摩擦吃掉 {friction_ratio:.0f}% 潜在利润" if friction_ratio else "无可测量 edge",
            "volume": m.volume,
            "days_to_resolution": m.days_to_resolution,
            "total_bid_depth_usd": m.total_bid_depth_usd,
            "total_ask_depth_usd": m.total_ask_depth_usd,
            "resolution_source": m.resolution_source,
            "structure_score": s.total,
            "mispricing_signal": mp.signal,
            "mispricing_direction": mp.direction,
            "mispricing_details": mp.details,
            "theoretical_fair_value": mp.theoretical_fair_value,
            "model_confidence": mp.model_confidence,
        }
        prompt = f"请对以下市场做决策分析:\n{json.dumps(data, default=str, ensure_ascii=False)}"
        if include_bias:
            prompt += "\n\n请额外输出 bias 字段（方向倾向的条件建议）。格式：{direction: lean_yes/lean_no/neutral, reasoning, confidence, caveat}"
        else:
            prompt += "\n\nbias 字段设为 null。"
        return prompt

    def _fallback_from_prompt(self, prompt: str) -> dict:
        from scanner.utils import extract_market_id_from_prompt
        market_id = extract_market_id_from_prompt(prompt)
        return NarrativeWriterOutput(
            market_id=market_id,
            action="watch_only",
            action_reasoning="AI 分析不可用",
            confidence="low",
            time_window=TimeWindow(urgency="normal", note=""),
            friction_impact="",
            summary="AI 分析不可用，请手动查看市场详情。",
            risk_flags=[RiskFlag(text="AI 分析不可用 — 仅基于规则判断", severity="warning")],
            counterparty_note="",
            research_findings=[],
            one_line_verdict="AI 离线，请手动评估。",
        ).model_dump()


def narrative_fallback(candidate: ScoredCandidate) -> NarrativeWriterOutput:
    """Rule-based fallback when AI agent is unavailable."""
    m = candidate.market
    s = candidate.score
    mp = candidate.mispricing

    # Determine action based on friction vs edge
    friction = m.round_trip_friction_pct or 0.04
    edge = mp.deviation_pct or 0
    friction_ratio = friction / edge if edge > 0 else float("inf")

    if friction_ratio > 0.8:
        action = "avoid"
    elif friction_ratio > 0.5:
        action = "watch_only"
    elif edge > 0.03:
        action = "small_position_ok"
    else:
        action = "worth_research"

    # Build risk flags with severity
    risks = []
    if friction:
        severity = "critical" if friction_ratio > 0.5 else "warning"
        risks.append(RiskFlag(text=f"摩擦 ~{friction:.1%}，吃掉潜在利润", severity=severity))
    if mp.signal == "none":
        risks.append(RiskFlag(text="未检测到定价偏差 — 市场可能已有效定价", severity="warning"))
    if m.total_bid_depth_usd and m.total_bid_depth_usd < 1000:
        risks.append(RiskFlag(text=f"买方深度不足 (${m.total_bid_depth_usd:.0f}) — 退出可能困难", severity="warning"))
    if not risks:
        risks.append(RiskFlag(text="请仔细阅读结算规则", severity="info"))

    # Time window
    days = m.days_to_resolution
    if days and days < 1:
        urgency = "urgent"
    elif days and days < 3:
        urgency = "normal"
    else:
        urgency = "no_rush"

    # Summary
    parts = [f"{'二元' if m.is_binary else '多选项'} {m.market_type or '市场'}"]
    if days:
        parts.append(f"{days:.1f} 天后结算")
    if mp.signal != "none":
        parts.append(f"{mp.signal} 定价偏差信号")
    summary = f"{', '.join(parts)}。结构分 {s.total:.0f}/100。"

    friction_impact = f"摩擦吃掉 {friction_ratio:.0%} 潜在利润" if edge > 0 else "无可测量 edge"

    return NarrativeWriterOutput(
        market_id=m.market_id,
        action=action,
        action_reasoning=f"摩擦 {friction:.1%} vs edge {edge:.1%}" if edge > 0 else "无可测量定价偏差",
        confidence="low",
        time_window=TimeWindow(
            urgency=urgency,
            note=f"还剩 {days:.1f} 天" if days else "结算时间未知",
        ),
        friction_impact=friction_impact,
        summary=summary,
        risk_flags=risks,
        counterparty_note=f"市场类型 '{m.market_type}' — 需手动评估对手方质量。",
        research_findings=[],
        one_line_verdict=f"{action}: {summary}",
        suggested_style="watch_only" if action in ("watch_only", "avoid") else "research_candidate",
    )
