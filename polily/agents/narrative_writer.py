"""NarrativeWriter Agent: autonomous decision analysis with tool access.

v0.12.0 — markdown mode:
  - BaseAgent constructed with json_schema=None → invoke() returns raw markdown str.
  - 4-part prompt assembly: per-call ephemeral → static manual → active strategy → protocol footer.
  - Output parsed into AgentMarkdownOutput (frontmatter dict + body str).
  - Persistence stores raw markdown via append_analysis(narrative_format="markdown").
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

import polily
from polily.agents.base import BaseAgent
from polily.agents.schemas import AgentMarkdownOutput
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB
from polily.core.strategy_store import get_active_strategy_text

logger = logging.getLogger(__name__)

# v0.12.0: dropped "StructuredOutput" — agent now emits free-form markdown
# with YAML frontmatter (see polily/agents/protocol.md). Read is required
# for the fallback path (manual.md §7 instructs the agent to load
# default.md when the active user strategy is unusable).
AGENT_TOOLS = ["Read", "Bash", "Grep", "WebSearch", "TodoWrite"]


class NarrativeWriterAgent:
    """Decision advisor agent with autonomous research capabilities.

    Uses claude -p with --allowedTools to:
    - Read polily.db for all event/market/position data
    - Search the web for news and prices
    - Output free-form markdown body + YAML frontmatter (v0.12.0)
    """

    def __init__(self, config: AgentConfig):
        self.config = config
        # v0.8.0 contract: no silent fallback. CLI invocation failures and
        # output parsing failures propagate so `PolilyService.analyze_event`'s
        # exception handler can mark the scan_logs row as status='failed'
        # instead of storing a degraded "completed" analysis version that
        # misleads the user.
        #
        # v0.12.0: system_prompt="" because the entire prompt is assembled
        # per-call by _build_prompt (4-part composition). json_schema=None
        # puts BaseAgent into markdown mode (Task 11.5) — invoke() returns
        # the raw `result` string verbatim instead of extracting JSON.
        self._agent = BaseAgent(
            system_prompt="",
            json_schema=None,
            model=config.model,
            timeout_seconds=config.timeout_seconds,
            max_prompt_chars=config.max_prompt_chars,
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
        db: PolilyDB,
    ) -> AgentMarkdownOutput:
        """Generate analysis with semantic validation + retry.

        v0.12.0:
          - prompt is now 4-part assembled (ephemeral + manual + strategy + protocol)
          - BaseAgent.invoke() returns raw markdown str (json_schema=None)
          - Parsed into AgentMarkdownOutput via _parse_output
          - The full raw markdown (with frontmatter) is attached to the
            returned output via ``raw_markdown`` attribute so PolilyService
            can persist it post atomic-claim with narrative_format='markdown'.

        Persistence is intentionally NOT done here: PolilyService.analyze_event
        gates persistence on an atomic ``finish_scan`` UPDATE so cancelled-mid-run
        narrator output does NOT land in the analyses table. Persisting from
        inside generate() would break that contract (see
        tests/test_analyze_event_lifecycle.py::test_analyze_skips_next_pending_when_cancelled_mid_run).
        """
        prompt = self._build_prompt(
            event_id=event_id,
            has_position=has_position,
            position_summary=position_summary,
            db=db,
            trigger_source=trigger_source,
        )

        last_output: AgentMarkdownOutput | None = None
        last_raw: str | None = None
        for attempt in range(2):  # 1 initial + 1 retry
            actual_prompt = prompt
            if attempt > 0 and last_output is not None:
                errors = last_output.semantic_errors()
                actual_prompt = (
                    f"{prompt}\n\n"
                    f"--- 上次输出不完整，请补充以下缺失字段 ---\n"
                    f"问题: {'; '.join(errors)}\n"
                    f"上次输出预览: {(last_raw or '')[:2000]}\n"
                    f"请重新生成完整的 frontmatter + markdown body。"
                )
                logger.info("Semantic retry for %s: %s", event_id, errors)

            raw: str = await self._agent.invoke(actual_prompt, on_heartbeat=on_heartbeat)
            try:
                output = self._parse_output(raw)
            except Exception as e:
                from polily.agents.base import _dump_debug
                _dump_debug("md_parse_fail", f"{e}\n---raw---\n{raw}")
                # v0.8.0 contract preserved: raise instead of returning a
                # fake fallback. Calling analyze_event will catch this and
                # flip scan_logs row to 'failed'.
                raise RuntimeError(
                    f"narrator markdown output failed parsing: {e}; "
                    f"raw preview: {str(raw)[:200]}",
                ) from e

            # Attach the raw markdown (with frontmatter) so PolilyService can
            # persist it verbatim via append_analysis(narrative_format='markdown').
            # Pydantic v2 with extra='ignore' rejects unknown fields at __init__
            # but allows attribute attachment via object.__setattr__.
            object.__setattr__(output, "raw_markdown", raw)

            errors = output.semantic_errors()
            if not errors:
                _write_dev_feedback(event_id, event_title, output, trigger_source)
                return output
            last_output = output
            last_raw = raw

        # Retries exhausted — return last output (partial is better than fallback).
        if last_output is not None:
            _write_dev_feedback(event_id, event_title, last_output, trigger_source)
        return last_output  # type: ignore[return-value]

    def _build_prompt(
        self,
        event_id: str,
        has_position: bool = False,
        position_summary: str | None = None,
        *,
        db: PolilyDB,
        trigger_source: str = "manual",
    ) -> str:
        """v0.12.0 prompt assembly — 4-part composition.

        Order: per-call ephemeral → static manual → active strategy → protocol footer.

        position_summary is treated as a raw fact in the per-call ephemeral
        block (Q4: facts injected, strategy interprets — no mode abstraction).

        i18n: language directive comes from the active catalog's
        `language.directive_for_llm` key so the LLM responds in the same
        language the user reads in the TUI. Injected per-call rather than
        baked into a static prompt because the user can switch language at
        runtime via F2.
        """
        from polily.tui.i18n import t

        # 1. Per-call ephemeral (the only block that varies per call)
        now_utc = datetime.now(UTC)
        local_now = now_utc.astimezone()
        try:
            language_directive = t("language.directive_for_llm")
        except Exception:
            language_directive = "Output language: follow the user's TUI language preference."

        polily_root = Path(polily.__file__).parent
        official_strategy_path = str(polily_root / "strategies" / "default.md")

        ephemeral_lines = [
            f"language_directive: {language_directive!r}",
            f"event_id: {event_id}",
            f"trigger: {trigger_source}",
            f"timestamp_utc: {now_utc.isoformat()}",
            f"timestamp_local: {local_now.isoformat()}",
            f"has_position: {str(has_position).lower()}",
            f'official_strategy_path: "{official_strategy_path}"',
        ]
        if has_position and position_summary:
            ephemeral_lines.append(f"position_summary: {position_summary!r}")
        ephemeral = "\n".join(ephemeral_lines)

        # 2. System manual (static, generated from skill_sources)
        manual = (polily_root / "agents" / "manual.md").read_text(encoding="utf-8")

        # 3. Active strategy (per radio: official | user)
        strategy = get_active_strategy_text(db)

        # 4. Protocol footer (static — locked frontmatter contract)
        protocol = (polily_root / "agents" / "protocol.md").read_text(encoding="utf-8")

        return f"{ephemeral}\n\n---\n\n{manual}\n\n---\n\n{strategy}\n\n---\n\n{protocol}"

    def _parse_output(self, raw: str) -> AgentMarkdownOutput:
        """Split agent's frontmatter + body into AgentMarkdownOutput.

        Defensive: missing/malformed frontmatter yields empty fields
        (semantic_errors() will flag missing next_check_at downstream).

        v0.12.0 hotfix: when split_frontmatter returns {} (no valid YAML
        mapping found), emit a WARNING with a raw-output preview. This is
        a bright-line signal that the agent violated the output protocol
        — without the warning, downstream effects (daemon next_check_at
        scheduling, dev_feedback collection) silently degrade.
        """
        from polily.agents.frontmatter import split_frontmatter

        fm, body = split_frontmatter(raw)
        if not fm:
            preview = raw[:200].replace("\n", "\\n")
            logger.warning(
                "Agent output had no valid YAML frontmatter — protocol drift; "
                "next_check_at / urgency / dev_feedback will be empty. "
                "Raw preview: %s",
                preview,
            )
        return AgentMarkdownOutput(
            markdown_body=body,
            next_check_at=str(fm.get("next_check_at", "")),
            next_check_reason=str(fm.get("next_check_reason", "")),
            urgency=str(fm.get("urgency", "normal")),
            dev_feedback=str(fm.get("dev_feedback", "")),
        )


def _write_dev_feedback(
    event_id: str,
    event_title: str | None,
    output: AgentMarkdownOutput,
    trigger_source: str,
) -> None:
    """Append agent feedback to data/logs/agent_feedback.log.

    v0.12.0: AgentMarkdownOutput exposes ``dev_feedback`` (single string)
    and ``markdown_body`` — no structured operations list. We log
    ``body_chars`` instead of the v0.11.x ``ops=`` summary so the log
    retains a context-density indicator the maintainer can scan.

    Header format: ``=== [UTC: ... | local: ...] trigger=X polily=vY
    event=Z title="T" body_chars=N ===``.

    Trigger label, 'local' label, and 'body_chars' all stay English by
    user decision (matches the rest of the log, which is English-only
    for grep-friendliness).
    """
    feedback = (output.dev_feedback or "").strip()
    if not feedback:
        return
    try:
        import polily as _polily
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
        body_chars = len(output.markdown_body or "")
        with open(log_path, "a") as f:
            f.write(
                f'\n=== [UTC: {utc_str} | local: {local_str}] '
                f'trigger={trigger_source} '
                f'polily=v{_polily.__version__} '
                f'event={event_id} title="{title}" body_chars={body_chars} ===\n'
            )
            f.write(f"{feedback}\n")
    except Exception:
        pass
