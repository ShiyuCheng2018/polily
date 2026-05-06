"""NarrativeWriter Agent: autonomous decision analysis with tool access."""

import json
import logging
from pathlib import Path

from polily.agents.base import BaseAgent
from polily.agents.schemas import NarrativeWriterOutput
from polily.core.config import AgentConfig

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
        # v0.8.0 contract: no silent fallback. CLI invocation failures and
        # schema-validation failures propagate so `PolilyService.analyze_event`'s
        # exception handler can mark the scan_logs row as status='failed'
        # instead of storing a degraded "completed" analysis version that
        # misleads the user. (The old BaseAgent.fallback_fn parameter was
        # dropped entirely in v0.9.0.)
        self._agent = BaseAgent(
            system_prompt=SYSTEM_PROMPT,
            json_schema=NarrativeWriterOutput.model_json_schema(),
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            max_prompt_chars=config.max_prompt_chars,  # NEW (Phase 0 Task 13)
            allowed_tools=AGENT_TOOLS,
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
        trigger_source: str,
        frozen_prices: dict[str, dict[str, float]] | None = None,
    ) -> NarrativeWriterOutput:
        """Generate analysis with semantic validation + retry.

        v0.11.7 (AF-1): `frozen_prices` is a snapshot of market prices
        captured by the caller BEFORE the agent runs. When provided,
        `_build_prompt` embeds them in a YAML block so the agent reads
        them from prompt text and does not re-query the markets table.
        """
        prompt = self._build_prompt(
            event_id, has_position, position_summary,
            frozen_prices=frozen_prices,
        )

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
                from polily.agents.base import _dump_debug
                _dump_debug("schema_fail", f"{e}\n---raw---\n{raw}")
                # v0.8.0: raise instead of returning a fake fallback
                # output. The calling `analyze_event` will catch this
                # and flip scan_logs row to 'failed', which is the
                # truthful state — the AI output was unusable.
                raise RuntimeError(
                    f"narrator output failed schema validation: {e}; "
                    f"raw preview: {str(raw)[:200]}",
                ) from e

            errors = output.semantic_errors()
            if not errors:
                _write_dev_feedback(event_id, event_title, output, trigger_source)
                return output
            last_output = output

        # Retries exhausted — return last output (partial is better than fallback)
        _write_dev_feedback(event_id, event_title, last_output, trigger_source)
        return last_output

    def _build_prompt(
        self,
        event_id: str,
        has_position: bool = False,
        position_summary: str | None = None,
        *,
        frozen_prices: dict[str, dict[str, float]] | None = None,
    ) -> str:
        """Build minimal prompt — agent reads DB and searches web on its own.

        i18n: prepends a self-describing language directive (loaded from the
        active catalog's `language.directive_for_llm` key) so the LLM
        responds in the same language the user reads in the TUI. This is
        injected per-call rather than baked into the system prompt because
        the user can switch language at runtime — and because the system
        prompt is loaded once at agent construction.

        v0.11.7 (AF-1): when `frozen_prices` is provided, render them at
        the top as a YAML block — the agent reads from prompt text instead
        of running `sqlite3 ... FROM markets`. Combined with deletion of
        the three FROM markets templates from narrative_writer.md, this
        becomes the single source of truth for prices the agent sees,
        eliminating cross-paragraph price drift (event 57711 v5 was the
        reproduced incident).
        """
        from polily.tui.i18n import t

        mode = "position_management" if has_position else "discovery"

        from datetime import UTC, datetime
        now_utc = datetime.now(UTC)
        local_now = now_utc.astimezone()
        local_tz_name = local_now.tzname() or "local"
        utc_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%S+00:00")
        local_str = local_now.strftime("%Y-%m-%d %H:%M %Z")

        language_directive = t("language.directive_for_llm")

        # AF-1: prepend frozen prices block (empty string when none).
        prices_section = self._render_frozen_prices_section(frozen_prices)

        prompt = f"""{prices_section}{language_directive}

分析事件 {event_id}。

模式: {mode}
数据库: data/polily.db
Prompt 指令: polily/agents/prompts/narrative_writer.md

当前时间:
  - UTC: {utc_iso} ← 数据库记录的时间一律是这个时区
  - 用户本地: {local_str}（{local_tz_name}）

时间使用规则：
- next_check_at 字段：必须用 UTC ISO 8601，格式如 "2026-04-29T08:00:00+00:00"（与 DB 对齐）
- 分析文字（analysis / summary / next_check_reason）：用用户本地时间表达，让用户读得自然
- 比如 "FOMC 4月29日 ET 14:00（北京时间约凌晨 02:00）" 这种双时区表述就是好的"""

        if has_position and position_summary:
            prompt += f"\n\n用户当前持仓:\n{position_summary}"
        elif not has_position:
            prompt += "\n\n用户在此事件无持仓。判断这个事件值不值得做，不值得就直接 PASS，值得再说具体怎么做。"

        return prompt

    @staticmethod
    def _render_frozen_prices_section(
        frozen_prices: dict[str, dict[str, float]] | None,
        captured_at: str | None = None,
    ) -> str:
        """Render the frozen prices block as a leading prompt section.

        Returns empty string if no frozen_prices provided (legacy fallback;
        callers post-v0.11.7 should always supply them, but this keeps
        the API forgiving for unit tests of `_build_prompt`).

        Whis-review SG-2 (2026-05-07): `captured_at` is an explicit param
        (default `None` → `datetime.now(UTC)`) so tests can supply a
        deterministic timestamp instead of asserting against a flaky
        wall-clock value. Production callers leave it None.
        """
        if not frozen_prices:
            return ""

        if captured_at is None:
            from datetime import UTC, datetime
            captured_at = datetime.now(UTC).isoformat()

        lines = [
            "## 价格快照（已冻结）",
            "",
            "**重要**: 以下价格已在分析开始时冻结。**不要重新查询 `markets` 表**——",
            "这些是本次分析依据的真实快照。任何叙述里引用的 `yes_price` / `no_price`",
            "都必须使用下面的值，否则会出现自相矛盾的报告。",
            "",
            "```yaml",
            f"prices_snapshot_at: {captured_at}",
            "markets:",
        ]
        for market_id, prices in frozen_prices.items():
            yes = prices.get("yes")
            no = prices.get("no")
            yes_str = f"{yes:.4f}" if yes is not None else "null"
            no_str = f"{no:.4f}" if no is not None else "null"
            lines.append(f"  {market_id}: {{yes: {yes_str}, no: {no_str}}}")
        lines.extend(["```", "", ""])
        return "\n".join(lines)


def _write_dev_feedback(
    event_id: str,
    event_title: str | None,
    output: NarrativeWriterOutput,
    trigger_source: str,
) -> None:
    """Append agent feedback to data/logs/agent_feedback.log.

    v0.10.1: header now includes trigger_source ('manual' / 'scan' /
    'scheduled' / 'movement') and dual UTC + local timestamps for
    cross-timezone post-mortem debugging. Trigger label and 'local'
    label both stay English by user decision (matches the rest of
    the log, which is English-only for grep-friendliness).
    """
    feedback = output.dev_feedback
    if not feedback:
        return
    try:
        from datetime import UTC, datetime

        import polily
        from polily.core import paths

        log_path = paths.agent_feedback_log()
        # paths.log_dir() (called inside agent_feedback_log) handles mkdir.
        now_utc = datetime.now(UTC)
        now_local = now_utc.astimezone()
        utc_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        local_str = now_local.strftime("%Y-%m-%d %H:%M:%S %Z")
        title = (
            (event_title or "?")
            .replace("\n", " ")
            .replace("\r", " ")
            .replace('"', "'")
        )
        with open(log_path, "a") as f:
            ops_summary = ",".join(op.action for op in output.operations) or "none"
            f.write(
                f'\n=== [UTC: {utc_str} | local: {local_str}] '
                f'trigger={trigger_source} '
                f'polily=v{polily.__version__} '
                f'event={event_id} title="{title}" ops={ops_summary} ===\n'
            )
            f.write(f"{feedback}\n")
    except Exception:
        pass


