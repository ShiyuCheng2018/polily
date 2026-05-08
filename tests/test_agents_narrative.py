"""Tests for NarrativeWriter agent.

v0.12.0: agent now emits free-form markdown body + YAML frontmatter
(AgentMarkdownOutput, not NarrativeWriterOutput). The CLI response is
just the raw markdown text in the ``result`` field — no
``structured_output`` envelope, no ``--json-schema`` flag.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.agents.schemas import AgentMarkdownOutput
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB

# Sample frontmatter + body the agent now emits.
SAMPLE_MARKDOWN = """---
next_check_at: "2026-04-12T12:00:00+00:00"
next_check_reason: "Monitor friction levels"
urgency: "normal"
dev_feedback: "[9/10] Schema clear; data fresh."
---

# Edge assessment — BTC > $88K

## Operations
BUY_YES @ 0.62 — moderate mispricing with edge after friction.

## Analysis
BTC approaching threshold with momentum.

## Risk
Round-trip friction eats most edge.
"""


def _make_cli_markdown_response(markdown: str) -> bytes:
    """Simulate claude CLI v2.1+ JSON output for markdown (no schema) mode.

    With ``json_schema=None``, BaseAgent passes ``--output-format json`` but
    NOT ``--json-schema`` — the agent's reply lands in the ``result`` field
    verbatim (no ``structured_output`` envelope).
    """
    return json.dumps(
        [
            {"type": "system", "subtype": "init", "cwd": "/test", "session_id": "test"},
            {
                "type": "result",
                "subtype": "success",
                "result": markdown,
                "session_id": "test",
            },
        ]
    ).encode()


class TestNarrativeWriterAgent:
    @pytest.mark.asyncio
    async def test_generate_narrative(self, tmp_path):
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        db = PolilyDB(tmp_path / "polily.db")

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                _make_cli_markdown_response(SAMPLE_MARKDOWN), b""
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.generate(
                event_id="ev_test", trigger_source="manual", db=db,
            )
            assert isinstance(result, AgentMarkdownOutput)
            # Frontmatter parsed into typed fields
            assert result.next_check_at == "2026-04-12T12:00:00+00:00"
            assert result.next_check_reason == "Monitor friction levels"
            assert result.urgency == "normal"
            # Body content survives verbatim, frontmatter stripped
            assert "Edge assessment — BTC" in result.markdown_body
            assert "BUY_YES @ 0.62" in result.markdown_body
            assert "frontmatter" not in result.markdown_body  # fence consumed
            # Raw markdown attached for downstream persistence by PolilyService
            assert getattr(result, "raw_markdown", None) == SAMPLE_MARKDOWN

    @pytest.mark.asyncio
    async def test_cli_failure_raises_not_fallback(self, tmp_path):
        """v0.8.0: narrator no longer masquerades CLI failures as a
        degraded "completed" analysis. CLI failures must surface as
        exceptions so `PolilyService.analyze_event`'s error handler can
        mark the scan_logs row as status='failed'."""
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        db = PolilyDB(tmp_path / "polily.db")

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            with pytest.raises(Exception):  # noqa: B017 — base agent raises arbitrary Exception on retry-exhaust
                await agent.generate(
                    event_id="ev_test", trigger_source="manual", db=db,
                )

    @pytest.mark.asyncio
    async def test_short_body_yields_partial_output_after_retry(self, tmp_path):
        """v0.12.0: parse never raises on short body — semantic_errors() flags
        it. Retry-exhaust returns the (semantically-flawed) last output rather
        than throwing, matching v0.11.x's "partial > fallback" contract.

        Replaces v0.11.x ``test_schema_validation_failure_raises_not_fallback``
        which asserted hard-raise on schema fail. Markdown mode has no
        schema; the equivalent failure mode is ``semantic_errors()``-flagged
        output, which is returned (not raised).
        """
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))
        db = PolilyDB(tmp_path / "polily.db")

        # frontmatter present but body too short — semantic_errors flags it
        bad_md = (
            '---\nnext_check_at: "2099-01-01T00:00:00+00:00"\n'
            'next_check_reason: "r"\n---\n\nx'
        )
        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                _make_cli_markdown_response(bad_md), b"",
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.generate(
                event_id="ev_test", trigger_source="manual", db=db,
            )
            # Returned (not raised); caller can inspect semantic_errors().
            assert isinstance(result, AgentMarkdownOutput)
            assert result.semantic_errors()  # body too short flagged


@pytest.fixture
def feedback_log_path(tmp_path, monkeypatch):
    """v0.11.0: redirect _write_dev_feedback's output via POLILY_DATA_DIR
    env, replacing the prior chdir + tmp_path/'data'/'logs' assertion
    pattern. After Task 4, _write_dev_feedback writes to
    paths.agent_feedback_log() which resolves via env, not cwd."""
    from polily.core import paths
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "data"))
    yield paths.agent_feedback_log()
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


class TestDevFeedbackLogFormat:
    def test_header_includes_polily_version_and_event_title(self, feedback_log_path):
        """Header line carries polily version + event title alongside body_chars.

        v0.12.0: ``ops=`` summary replaced with ``body_chars=`` since
        AgentMarkdownOutput has no structured operations list. Other
        invariants (polily version, event title quoting) preserved.
        """
        import polily
        from polily.agents.narrative_writer import _write_dev_feedback

        body = "# Long enough body for the test"
        output = AgentMarkdownOutput(
            markdown_body=body,
            next_check_at="2099-01-01T00:00:00+00:00",
            next_check_reason="r",
            dev_feedback="[9/10] 全对",
        )
        _write_dev_feedback("357807", "Iran Hormuz closure 2025", output, trigger_source="manual")

        log = feedback_log_path.read_text()
        assert f"polily=v{polily.__version__}" in log
        assert "event=357807" in log
        assert 'title="Iran Hormuz closure 2025"' in log
        assert f"body_chars={len(body)}" in log
        assert "[9/10] 全对" in log

    def test_header_title_missing_renders_placeholder(self, feedback_log_path):
        from polily.agents.narrative_writer import _write_dev_feedback

        output = AgentMarkdownOutput(
            markdown_body="# adequate length body content",
            next_check_at="2099-01-01T00:00:00+00:00",
            next_check_reason="r",
            dev_feedback="note",
        )
        _write_dev_feedback("x", None, output, trigger_source="manual")

        log = feedback_log_path.read_text()
        assert 'title="?"' in log

    def test_header_title_sanitizes_newlines_and_quotes(self, feedback_log_path):
        """Newlines/CRs/quotes in user-controlled title must not split the header."""
        from polily.agents.narrative_writer import _write_dev_feedback

        output = AgentMarkdownOutput(
            markdown_body="# adequate length body content",
            next_check_at="2099-01-01T00:00:00+00:00",
            next_check_reason="r",
            dev_feedback="note",
        )
        _write_dev_feedback("y", 'Iran\n"hormuz"\rclosure', output, trigger_source="manual")

        log = feedback_log_path.read_text()
        # Header must stay on one line and double-quotes swapped to single
        header_line = next(line for line in log.splitlines() if line.startswith("==="))
        assert "event=y" in header_line
        assert "title=\"Iran 'hormuz' closure\"" in header_line
