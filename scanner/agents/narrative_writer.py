"""NarrativeWriter Agent: autonomous decision analysis with tool access."""

import json
import logging
from pathlib import Path

from scanner.agents.base import BaseAgent
from scanner.agents.schemas import NarrativeWriterOutput, RiskFlag
from scanner.core.config import AgentConfig

logger = logging.getLogger(__name__)

PROMPT_FILE = Path(__file__).parent / "prompts" / "narrative_writer.md"
if PROMPT_FILE.exists():
    SYSTEM_PROMPT = PROMPT_FILE.read_text()
else:
    logger.warning("Prompt file not found: %s — using minimal fallback prompt", PROMPT_FILE)
    SYSTEM_PROMPT = "You are a Polymarket trading analyst."

# Tools the agent can use for research
AGENT_TOOLS = ["Read", "Bash", "Grep", "WebSearch", "TodoWrite", "StructuredOutput"]


class NarrativeWriterAgent:
    """Decision advisor agent with autonomous research capabilities.

    Uses claude -p with --allowedTools to:
    - Read polily.db for all event/market/position data
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

    async def generate(
        self,
        event_id: str,
        has_position: bool = False,
        position_summary: str | None = None,
        on_heartbeat=None,
        *,
        event_title: str | None = None,
    ) -> NarrativeWriterOutput:
        """Generate analysis with semantic validation + retry."""
        prompt = self._build_prompt(event_id, has_position, position_summary)

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
                logger.info("Semantic retry for %s: %s", event_id, errors)

            raw = await self._agent.invoke(actual_prompt, on_heartbeat=on_heartbeat)
            try:
                output = NarrativeWriterOutput.model_validate(raw)
            except Exception as e:
                from scanner.agents.base import _dump_debug
                _dump_debug("schema_fail", f"{e}\n---raw---\n{raw}")
                return narrative_fallback(event_id)

            errors = output.semantic_errors()
            if not errors:
                _write_dev_feedback(event_id, event_title, output)
                return output
            last_output = output

        # Retries exhausted — return last output (partial is better than fallback)
        _write_dev_feedback(event_id, event_title, last_output)
        return last_output

    def _build_prompt(
        self,
        event_id: str,
        has_position: bool = False,
        position_summary: str | None = None,
    ) -> str:
        """Build minimal prompt — agent reads DB and searches web on its own."""
        mode = "position_management" if has_position else "discovery"

        from datetime import datetime
        local_tz = datetime.now().astimezone().tzname()
        local_now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")

        prompt = f"""分析事件 {event_id}。

模式: {mode}
数据库: data/polily.db
Prompt 指令: scanner/agents/prompts/narrative_writer.md
当前时间: {local_now}（用户时区 {local_tz}，分析文字里用本地时间）"""

        if has_position and position_summary:
            prompt += f"\n\n用户当前持仓:\n{position_summary}"
        elif not has_position:
            prompt += "\n\n用户在此事件无持仓。判断这个事件值不值得做，不值得就直接 PASS，值得再说具体怎么做。"

        return prompt

    def _fallback_from_prompt(self, prompt: str) -> dict:
        from scanner.utils import extract_event_id_from_prompt
        event_id = extract_event_id_from_prompt(prompt)
        return NarrativeWriterOutput(
            event_id=event_id,
            mode="discovery",
            summary="AI 分析不可用，请手动查看。",
            risk_flags=[RiskFlag(text="AI 不可用", severity="warning")],
        ).model_dump()


def _write_dev_feedback(
    event_id: str,
    event_title: str | None,
    output: NarrativeWriterOutput,
) -> None:
    """Append agent feedback to data/logs/agent_feedback.log."""
    feedback = output.dev_feedback
    if not feedback:
        return
    try:
        import os
        from datetime import UTC, datetime

        import scanner

        log_dir = os.path.join(os.getcwd(), "data", "logs")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        title = (
            (event_title or "?")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace('"', "'")
        )
        with open(os.path.join(log_dir, "agent_feedback.log"), "a") as f:
            ops_summary = ",".join(op.action for op in output.operations) or "none"
            f.write(
                f'\n=== [{ts}] polily=v{scanner.__version__} '
                f'event={event_id} title="{title}" ops={ops_summary} ===\n'
            )
            f.write(f"{feedback}\n")
    except Exception:
        pass


def narrative_fallback(event_id: str) -> NarrativeWriterOutput:
    """Rule-based fallback when AI agent is unavailable."""
    from datetime import UTC, datetime, timedelta

    next_check = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    return NarrativeWriterOutput(
        event_id=event_id,
        mode="discovery",
        summary="AI 分析不可用，建议手动查看事件详情后决定。",
        risk_flags=[RiskFlag(text="AI 分析失败，结果不可靠", severity="warning")],
        next_check_at=next_check,
        next_check_reason="AI 失败后默认 24h 重试",
    )
