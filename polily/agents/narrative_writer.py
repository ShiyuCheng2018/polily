"""NarrativeWriter Agent: autonomous decision analysis with tool access.

v0.12.0 — markdown mode:
  - BaseAgent constructed with json_schema=None → invoke() returns raw markdown str.
  - 4-part prompt assembly: per-call ephemeral → static manual → active strategy → protocol footer.
  - Output parsed into AgentMarkdownOutput (frontmatter dict + body str).
  - Persistence stores raw markdown via append_analysis(narrative_format="markdown").

v0.12.x (T-1) — movement-triggered context injection:
  - When trigger_source == "movement", _build_prompt reverse-queries
    movement_log for the event's recent sub-market movements and injects
    a `triggering_movements:` subsection into the ephemeral block. Agent
    sees the cross-market story without having to query the DB itself.

v0.12.x (T-2) — event_metadata freshness injection:
  - _build_prompt always (when metadata exists) injects an
    `event_metadata_freshness:` block exposing polily-computed staleness
    (fresh / stale / very_stale) + Polymarket's `context_requires_regen`
    flag + an imperative guidance string. Agent no longer has to parse
    `context_updated_at` and compute age itself.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import polily
from polily.agents.base import BaseAgent
from polily.agents.schemas import AgentMarkdownOutput
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB
from polily.core.strategy_store import get_active_strategy_text

logger = logging.getLogger(__name__)

# v0.12.x (T-1): window for movement-trigger context injection. Matches the
# 60s cutoff `_check_event_trigger` uses in `polily/daemon/poll_job.py:993`
# so the prompt reflects the same data polily's decision logic saw.
# Dispatcher lag (typically 5-15s) keeps the execution-time reverse-query
# within this window for the trigger snapshot.
_MOVEMENT_CONTEXT_WINDOW_SECONDS = 60


def _fetch_recent_movements(
    event_id: str, db: PolilyDB, window_seconds: int = _MOVEMENT_CONTEXT_WINDOW_SECONDS,
) -> list[dict]:
    """Return per-sub-market movement_log rows for `event_id` within the
    last `window_seconds`, ordered by magnitude DESC (spike row first).

    Used by `_build_prompt` to inject `triggering_movements:` ephemeral
    context when `trigger_source == "movement"`. Event-level rows
    (market_id IS NULL) are excluded — we want per-market story, not
    aggregated metrics.

    Returns an empty list (not None) on no matches, so callers can
    branch on truthiness cleanly.
    """
    cutoff = (
        datetime.now(UTC) - timedelta(seconds=window_seconds)
    ).isoformat()
    with db.transaction() as conn:
        rows = conn.execute(
            """SELECT market_id, label, yes_price, prev_yes_price,
                      magnitude, quality
               FROM movement_log
               WHERE event_id = ?
                 AND market_id IS NOT NULL
                 AND created_at >= ?
               ORDER BY magnitude DESC, created_at DESC""",
            (event_id, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def _format_movement_line(m: dict) -> str:
    """Render one movement_log row as a `triggering_movements:` bullet.

    Format keeps to one line per market for the agent's scan-ability:
        - market_id: '...' label: ... yes: 0.30->0.40 M: 78 Q: 65

    Missing prices fall back to `?` so a partial snapshot still renders
    (rather than format-string crashing on None).
    """
    def _fmt_price(v: float | None) -> str:
        return f"{v:.2f}" if v is not None else "?"

    return (
        f"  - market_id: {m['market_id']!r} "
        f"label: {m['label']} "
        f"yes: {_fmt_price(m['prev_yes_price'])}->{_fmt_price(m['yes_price'])} "
        f"M: {m['magnitude']:.0f} Q: {m['quality']:.0f}"
    )


# v0.12.x (T-2): staleness thresholds for events.event_metadata. Matches
# default.md's "If context_updated_at is older than 24h, the description
# may be stale — supplement with WebSearch" guidance for the 24h boundary.
# 72h (3 days) escalates to mandatory WebSearch because agent dev_feedback
# (2026-05-15 on events 108031 / 73106 / 51456) caught content 5-6 days
# stale across multiple monitored events when Polymarket's
# context_requires_regen flag never fired.
_FRESH_HOURS = 24
_VERY_STALE_HOURS = 72


def _fetch_event_metadata_freshness(
    event_id: str, db: PolilyDB,
) -> dict | None:
    """Return a small dict describing the freshness of `events.event_metadata`
    for `event_id`, or None when metadata is missing / unparseable / lacks
    a usable `context_updated_at` timestamp.

    The dict has shape:
        {
            "context_updated_at": "<ISO string Polymarket reported>",
            "age_hours": <int — seconds-since rounded to hours>,
            "staleness": "fresh" | "stale" | "very_stale",
            "polymarket_flag_set": <bool — context_requires_regen value>,
            "guidance": "<imperative action string for the agent>",
        }

    Used by `_build_prompt` to inject `event_metadata_freshness:`
    ephemeral context. Unconditional injection (all trigger sources)
    because metadata staleness matters for any analysis path.
    """
    with db.transaction() as conn:
        row = conn.execute(
            "SELECT event_metadata FROM events WHERE event_id = ?",
            (event_id,),
        ).fetchone()
    if not row or not row["event_metadata"]:
        return None
    try:
        meta = json.loads(row["event_metadata"])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(meta, dict):
        return None
    ts_str = meta.get("context_updated_at")
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None

    age_seconds = (datetime.now(UTC) - ts).total_seconds()
    # Future timestamp (clock skew on Polymarket side) → treat as fresh
    # rather than emitting a negative age_hours which would confuse the agent.
    age_hours = max(int(age_seconds // 3600), 0)

    if age_hours < _FRESH_HOURS:
        staleness = "fresh"
        guidance = (
            "Metadata within 24h — safe to use as baseline understanding. "
            "WebSearch only for specific catalysts the description doesn't cover."
        )
    elif age_hours < _VERY_STALE_HOURS:
        staleness = "stale"
        guidance = (
            "Metadata 1-3 days old — supplement with WebSearch for recent "
            "developments before drawing conclusions. Do not treat the "
            "context_description as the latest reality."
        )
    else:
        staleness = "very_stale"
        guidance = (
            "Metadata >3 days old — DO NOT use context_description as "
            "authoritative baseline. WebSearch is MANDATORY to find "
            "catalysts and reframings since context_updated_at. Agent "
            "dev_feedback has caught 5+ day stale descriptions multiple "
            "times where Polymarket's regen flag never fired."
        )

    return {
        "context_updated_at": ts_str,
        "age_hours": age_hours,
        "staleness": staleness,
        "polymarket_flag_set": bool(meta.get("context_requires_regen")),
        "guidance": guidance,
    }

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

        # v0.12.x (T-2): expose polily-computed staleness for the event's
        # Polymarket-curated metadata. Unconditional (all trigger sources)
        # because metadata staleness applies to any analysis path. Agent
        # used to parse `context_updated_at` itself and decide WebSearch;
        # now polily labels it and gives an imperative guidance string.
        freshness = _fetch_event_metadata_freshness(event_id, db)
        if freshness:
            # Use !r consistently across user-controlled strings
            # (context_updated_at + staleness + guidance all come from
            # data we could in principle not trust at format-time).
            # !r emits a Python repr — single-quoted + escaped — which
            # is also valid YAML and prevents any embedded `"` from
            # breaking the structured block.
            ephemeral_lines.append("event_metadata_freshness:")
            ephemeral_lines.append(
                f"  context_updated_at: {freshness['context_updated_at']!r}"
            )
            ephemeral_lines.append(f"  age_hours: {freshness['age_hours']}")
            ephemeral_lines.append(
                f"  staleness: {freshness['staleness']!r}"
            )
            ephemeral_lines.append(
                f"  polymarket_flag_set: "
                f"{str(freshness['polymarket_flag_set']).lower()}"
            )
            ephemeral_lines.append(f"  guidance: {freshness['guidance']!r}")

        # v0.12.x (T-1): when polily auto-fired analysis because of detected
        # movement, inject the per-market trigger story so the agent can
        # reason about the cross-market picture without reverse-querying
        # movement_log itself. For manual / scan / scheduled triggers we
        # skip this — those have no "what just moved" semantic.
        if trigger_source == "movement":
            movements = _fetch_recent_movements(event_id, db)
            if movements:
                ephemeral_lines.append("triggering_movements:")
                ephemeral_lines.extend(_format_movement_line(m) for m in movements)

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
