"""NarrativeWriter Agent: autonomous decision analysis with tool access."""

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

# Tools the agent can use for research
AGENT_TOOLS = ["Read", "Bash", "Grep", "WebSearch", "StructuredOutput"]


class NarrativeWriterAgent:
    """Decision advisor agent with autonomous research capabilities.

    Uses claude -p with --allowedTools to:
    - Read polily.db for analysis history
    - Search the web for news and prices
    - Output structured decisions via StructuredOutput
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=NarrativeWriterOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            allowed_tools=AGENT_TOOLS,
            fallback_fn=lambda prompt: self._fallback_from_prompt(prompt),
        )

    def cancel(self):
        """Cancel the currently running analysis."""
        self._agent.cancel()

    async def generate(self, candidate: ScoredCandidate,
                       include_bias: bool = False,
                       on_heartbeat=None) -> NarrativeWriterOutput:
        """Generate analysis with semantic validation + retry."""
        prompt = self._build_prompt(candidate, include_bias=include_bias)

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

    def _build_prompt(self, candidate: ScoredCandidate, include_bias: bool = False) -> str:
        """Build minimal prompt — agent reads DB and searches web on its own."""
        m = candidate.market
        s = candidate.score
        mp = candidate.mispricing

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
            "resolution_time": m.resolution_time.isoformat() if m.resolution_time else None,
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

        prompt = f"""请分析市场 {m.market_id}。

指令文件: scanner/agents/prompts/narrative_writer.md
数据库: data/polily.db

当前市场数据:
{json.dumps(data, default=str, ensure_ascii=False)}"""

        if include_bias:
            prompt += "\n\n请额外输出 bias 字段（方向倾向的条件建议）。"
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

    if edge > 0 and friction < edge * 0.5:
        fve = "edge_exceeds"
    elif edge > 0 and friction < edge:
        fve = "roughly_equals"
    else:
        fve = "friction_exceeds"

    risks = []
    if friction:
        severity = "critical" if friction_ratio > 0.5 else "warning"
        risks.append(RiskFlag(text=f"摩擦 ~{friction:.1%}，吃掉潜在利润", severity=severity))
    if mp.signal == "none":
        risks.append(RiskFlag(text="未检测到定价偏差", severity="warning"))

    days = m.days_to_resolution
    urgency = "urgent" if days and days < 1 else "normal" if days and days < 3 else "no_rush"

    parts = [f"{'二元' if m.is_binary else '多选项'} {m.market_type or '市场'}"]
    if days:
        parts.append(f"{days:.1f} 天后结算")
    summary = f"{', '.join(parts)}。"

    why_not = ""
    if action in ("PASS", "WATCH"):
        if fve == "friction_exceeds":
            why_not = f"摩擦 {friction:.1%} 大于可测量 edge"
        elif mp.signal == "none":
            why_not = "未检测到定价偏差，市场可能已有效定价"
        else:
            why_not = "当前价格没有明显优势"

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
