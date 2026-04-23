"""Tests for NarrativeWriter agent."""

from unittest.mock import AsyncMock, patch

import pytest

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.agents.schemas import NarrativeWriterOutput
from polily.core.config import AgentConfig
from tests.conftest import make_cli_response_structured

SAMPLE_NARRATIVE_OUTPUT = {
    "event_id": "ev_test",
    "time_window": {"urgency": "normal", "note": "还剩 2.0 天"},
    "operations": [
        {
            "action": "BUY_YES",
            "market_id": "0xtest",
            "confidence": "medium",
            "market_title": "BTC > $88K",
            "entry_price": 0.62,
            "position_size_usd": 20,
            "reasoning": "Moderate mispricing with edge after friction",
        },
    ],
    "operations_commentary": "单一方向操作，仓位适中",
    "analysis": "BTC approaching threshold with momentum",
    "analysis_commentary": "技术面支撑，基本面中性",
    "summary": "Crypto market with moderate mispricing signal, edge after friction.",
    "risk_flags": [
        {"text": "Round-trip friction eats most edge", "severity": "critical"},
        {"text": "Bots dominate this market", "severity": "warning"},
    ],
    "risk_commentary": "摩擦是主要风险",
    "research_findings": [
        {"finding": "BTC 当前价格 $67,750", "source": "Binance", "impact": "距阈值 $88k 还有 23%"},
        {"finding": "若 BTC 突破 $70K", "source": "技术面", "impact": "YES 可能低估"},
    ],
    "research_commentary": "资讯支持方向但不确定",
    "next_check_at": "2026-04-12T12:00:00",
    "next_check_reason": "Monitor friction levels",
}


class TestNarrativeWriterAgent:
    @pytest.mark.asyncio
    async def test_generate_narrative(self):
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response_structured(SAMPLE_NARRATIVE_OUTPUT), b""
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.generate(event_id="ev_test")
            assert isinstance(result, NarrativeWriterOutput)
            assert result.event_id == "ev_test"
            assert len(result.operations) == 1
            assert result.operations[0].action == "BUY_YES"
            assert len(result.risk_flags) > 0
            assert len(result.research_findings) > 0

    @pytest.mark.asyncio
    async def test_cli_failure_raises_not_fallback(self):
        """v0.8.0: narrator no longer masquerades CLI failures as a
        degraded "completed" analysis. CLI failures must surface as
        exceptions so `PolilyService.analyze_event`'s error handler can
        mark the scan_logs row as status='failed'."""
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            with pytest.raises(Exception):  # noqa: B017 — base agent raises arbitrary Exception on retry-exhaust
                await agent.generate(event_id="ev_test")

    @pytest.mark.asyncio
    async def test_schema_validation_failure_raises_not_fallback(self):
        """Schema-invalid CLI output should raise, not return a fake
        "AI 不可用" NarrativeWriterOutput that ends up stored as a
        valid analysis version."""
        agent = NarrativeWriterAgent(AgentConfig(model="sonnet"))

        # CLI returns valid JSON wrapper but the `result` payload fails
        # `NarrativeWriterOutput.model_validate` (missing required fields).
        garbage = {"unexpected_field": "value"}
        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response_structured(garbage), b"",
            )
            proc.returncode = 0
            mock_exec.return_value = proc

            with pytest.raises(Exception):  # noqa: B017 — narrator raises RuntimeError via schema-fail wrapper
                await agent.generate(event_id="ev_test")


class TestDevFeedbackLogFormat:
    def test_header_includes_polily_version_and_event_title(self, tmp_path, monkeypatch):
        """Header line carries polily version + event title alongside ops summary.

        Before: `=== [ts] event=357807 ops=HOLD ===`
        After:  `=== [ts] polily=v0.6.1 event=357807 title="Iran" ops=HOLD ===`
        """
        import polily
        from polily.agents.narrative_writer import _write_dev_feedback
        from polily.agents.schemas import Operation

        monkeypatch.chdir(tmp_path)

        output = NarrativeWriterOutput(
            event_id="357807",
            mode="position_management",
            summary="s",
            operations=[Operation(action="HOLD", reasoning="r")],
            dev_feedback="[9/10] 全对",
        )
        _write_dev_feedback("357807", "Iran Hormuz closure 2025", output)

        log = (tmp_path / "data" / "logs" / "agent_feedback.log").read_text()
        assert f"polily=v{polily.__version__}" in log
        assert "event=357807" in log
        assert 'title="Iran Hormuz closure 2025"' in log
        assert "ops=HOLD" in log
        assert "[9/10] 全对" in log

    def test_header_title_missing_renders_placeholder(self, tmp_path, monkeypatch):
        from polily.agents.narrative_writer import _write_dev_feedback

        monkeypatch.chdir(tmp_path)
        output = NarrativeWriterOutput(
            event_id="x",
            mode="discovery",
            summary="s",
            dev_feedback="note",
        )
        _write_dev_feedback("x", None, output)

        log = (tmp_path / "data" / "logs" / "agent_feedback.log").read_text()
        assert 'title="?"' in log

    def test_header_title_sanitizes_newlines_and_quotes(self, tmp_path, monkeypatch):
        """Newlines/CRs/quotes in user-controlled title must not split the header."""
        from polily.agents.narrative_writer import _write_dev_feedback

        monkeypatch.chdir(tmp_path)
        output = NarrativeWriterOutput(
            event_id="y",
            mode="discovery",
            summary="s",
            dev_feedback="note",
        )
        _write_dev_feedback("y", 'Iran\n"hormuz"\rclosure', output)

        log = (tmp_path / "data" / "logs" / "agent_feedback.log").read_text()
        # Header must stay on one line and double-quotes swapped to single
        header_line = next(line for line in log.splitlines() if line.startswith("==="))
        assert "event=y" in header_line
        assert "title=\"Iran 'hormuz' closure\"" in header_line
