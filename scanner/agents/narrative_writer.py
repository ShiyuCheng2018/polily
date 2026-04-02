"""NarrativeWriter Agent: generate analysis narratives for scored candidates."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import NarrativeWriterOutput, RiskFlag, TimeWindow, WatchCondition
from scanner.config import AgentConfig
from scanner.reporting import ScoredCandidate

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "narrative_writer.md"
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

    def cancel(self):
        """Cancel the currently running analysis."""
        self._agent.cancel()

    async def generate(self, candidate: ScoredCandidate, context: str | None = None,
                       include_bias: bool = False,
                       on_heartbeat=None) -> NarrativeWriterOutput:
        """Generate narrative with semantic validation + error-context retry."""
        prompt = self._build_prompt(candidate, include_bias=include_bias)
        if context:
            prompt += f"\n\n{context}"

        last_output = None
        for attempt in range(2):  # 1 initial + 1 retry
            actual_prompt = prompt
            if attempt > 0 and last_output is not None:
                errors = last_output.semantic_errors()
                actual_prompt = (
                    f"{prompt}\n\n"
                    f"--- 上次输出不完整，请补充以下缺失字段 ---\n"
                    f"问题: {'; '.join(errors)}\n"
                    f"上次输出: {json.dumps(last_output.model_dump(), ensure_ascii=False, default=str)[:2000]}\n"
                    f"请重新生成完整 JSON。"
                )
                logger.info("Semantic retry for %s: %s", candidate.market.market_id, errors)

            raw = await self._agent.invoke(actual_prompt, on_heartbeat=on_heartbeat)
            try:
                output = NarrativeWriterOutput.model_validate(raw)
            except Exception as e:
                from scanner.agents.base import _dump_debug
                _dump_debug("schema_fail", f"{e}\n---raw---\n{raw}")
                return narrative_fallback(candidate)

            errors = output.semantic_errors()
            if not errors:
                return output
            last_output = output

        # Retries exhausted — return last output (partial is better than fallback)
        return last_output

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
        friction = m.round_trip_friction_pct if m.round_trip_friction_pct is not None else 0.04
        edge = mp.deviation_pct if mp.deviation_pct is not None else 0
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
            action="PASS",
            confidence="low",
            summary="AI 分析不可用，请手动查看。",
            risk_flags=[RiskFlag(text="AI 不可用", severity="warning")],
            one_line_verdict="AI 离线",
        ).model_dump()


def narrative_fallback(candidate: ScoredCandidate) -> NarrativeWriterOutput:
    """Rule-based fallback when AI agent is unavailable."""
    m = candidate.market
    mp = candidate.mispricing

    friction = m.round_trip_friction_pct if m.round_trip_friction_pct is not None else 0.04
    edge = mp.deviation_pct if mp.deviation_pct is not None else 0
    friction_ratio = friction / edge if edge > 0 else float("inf")

    # Action
    if friction_ratio > 0.8:
        action = "PASS"
    elif friction_ratio > 0.5:
        action = "WATCH"
    elif edge > 0.05 and mp.direction == "underpriced":
        action = "BUY_YES"
    elif edge > 0.05 and mp.direction == "overpriced":
        action = "BUY_NO"
    else:
        action = "WATCH"

    # Friction vs edge
    if edge > 0 and friction < edge * 0.5:
        fve = "edge_exceeds"
    elif edge > 0 and friction < edge:
        fve = "roughly_equals"
    else:
        fve = "friction_exceeds"

    # Risk flags
    risks = []
    if friction:
        severity = "critical" if friction_ratio > 0.5 else "warning"
        risks.append(RiskFlag(text=f"摩擦 ~{friction:.1%}，吃掉潜在利润", severity=severity))
    if mp.signal == "none":
        risks.append(RiskFlag(text="未检测到定价偏差", severity="warning"))

    # Time
    days = m.days_to_resolution
    urgency = "urgent" if days and days < 1 else "normal" if days and days < 3 else "no_rush"

    # Summary
    parts = [f"{'二元' if m.is_binary else '多选项'} {m.market_type or '市场'}"]
    if days:
        parts.append(f"{days:.1f} 天后结算")
    summary = f"{', '.join(parts)}。"

    # Why not now
    why_not = ""
    if action in ("PASS", "WATCH"):
        if fve == "friction_exceeds":
            why_not = f"摩擦 {friction:.1%} 大于可测量 edge"
        elif mp.signal == "none":
            why_not = "未检测到定价偏差，市场可能已有效定价"
        else:
            why_not = "当前价格没有明显优势"

    # Recheck + watch
    recheck = []
    watch = None
    if action == "WATCH":
        if m.yes_price:
            recheck.append(f"YES 回到 {m.yes_price * 0.85:.2f} 以下")
        recheck.append("出现明确催化事件")
        watch = WatchCondition(
            watch_reason=why_not or "当前不值得做",
            better_entry=f"YES <= {m.yes_price * 0.85:.2f}" if m.yes_price else "",
            trigger_event=recheck[0] if recheck else "",
            invalidation="距结算 <12h 且价格未变" if days else "",
        )

    return NarrativeWriterOutput(
        market_id=m.market_id,
        action=action,
        bias="NONE",
        strength="weak",
        confidence="low",
        opportunity_type="no_trade" if action == "PASS" else "watch_only" if action == "WATCH" else "slow_structure",
        time_window=TimeWindow(urgency=urgency, note=f"还剩 {days:.1f} 天" if days else ""),
        why_now="" if action in ("PASS", "WATCH") else "规则检测到可能的 edge",
        why_not_now=why_not,
        friction_vs_edge=fve,
        execution_risk="low",
        risk_flags=risks,
        counterparty_note=f"市场类型 '{m.market_type}'",
        recheck_conditions=recheck,
        watch=watch,
        next_step="pass_for_now" if action == "PASS" else f"watch_yes_below_{m.yes_price * 0.85:.2f}" if action == "WATCH" and m.yes_price else "",
        summary=summary,
        one_line_verdict=f"{action}: {summary}",
    )
