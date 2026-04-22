"""Tests for AI agent base: claude CLI invocation, fallback, JSON parsing."""

from unittest.mock import AsyncMock, patch

import pytest

from polily.agents.base import BaseAgent
from tests.conftest import make_cli_response


class TestBaseAgentInvoke:
    @pytest.mark.asyncio
    async def test_invoke_returns_structured_output(self):
        agent = BaseAgent(
            system_prompt="You are a test agent.",
            json_schema={"type": "object", "properties": {"score": {"type": "integer"}}},
            model="haiku",
        )
        expected = {"score": 42}
        stdout = make_cli_response(expected)

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.invoke("test prompt")
            assert result == expected

    @pytest.mark.asyncio
    async def test_invoke_passes_correct_cli_args(self):
        agent = BaseAgent(
            system_prompt="You are X.",
            json_schema={"type": "object"},
            model="sonnet",
        )
        stdout = make_cli_response({"ok": True})

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            await agent.invoke("hello")

            args = mock_exec.call_args[0]
            assert args[0] == "claude"
            assert "-p" in args
            assert "--output-format" in args
            assert "json" in args
            assert "--model" in args
            assert "sonnet" in args
            assert "--system-prompt" in args

    @pytest.mark.asyncio
    async def test_invoke_uses_file_for_large_input(self):
        """When prompt > max_prompt_chars, should write to temp file."""
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="haiku",
            max_prompt_chars=100,
        )
        long_prompt = "A" * 200
        stdout = make_cli_response({"ok": True})

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.invoke(long_prompt)
            assert result == {"ok": True}

            # The prompt arg should reference a file path, not the full text
            args = mock_exec.call_args[0]
            prompt_idx = list(args).index("-p") + 1
            prompt_arg = args[prompt_idx]
            assert "Analyze the data in file:" in prompt_arg or len(prompt_arg) < 200


class TestBaseAgentFallback:
    @pytest.mark.asyncio
    async def test_fallback_on_nonzero_exit(self):
        fallback_result = {"fallback": True}
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="haiku",
            fallback_fn=lambda prompt: fallback_result,
        )

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error occurred")
            proc.returncode = 1
            mock_exec.return_value = proc

            result = await agent.invoke("test")
            assert result == fallback_result

    @pytest.mark.asyncio
    async def test_fallback_on_invalid_json(self):
        fallback_result = {"fallback": True}
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="haiku",
            fallback_fn=lambda prompt: fallback_result,
        )

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"not json at all", b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            result = await agent.invoke("test")
            assert result == fallback_result

    @pytest.mark.asyncio
    async def test_raises_if_no_fallback(self):
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="haiku",
            fallback_fn=None,
        )

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"", b"error")
            proc.returncode = 1
            mock_exec.return_value = proc

            with pytest.raises(RuntimeError):
                await agent.invoke("test")


class TestBaseAgentToolMode:
    @pytest.mark.asyncio
    async def test_tool_mode_passes_allowed_tools(self):
        agent = BaseAgent(
            system_prompt="test",
            json_schema={"type": "object"},
            model="sonnet",
            allowed_tools=["Read", "Bash", "WebSearch", "StructuredOutput"],
        )
        stdout = make_cli_response({"ok": True})

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            await agent.invoke("test prompt")

            args = mock_exec.call_args[0]
            assert "--allowedTools" in args
            tools_idx = list(args).index("--allowedTools") + 1
            assert "Read" in args[tools_idx]
            assert "Bash" in args[tools_idx]
            assert "WebSearch" in args[tools_idx]
            # Tool mode should NOT use --bare (needs file access)
            assert "--bare" not in args

    @pytest.mark.asyncio
    async def test_legacy_mode_uses_bare(self):
        agent = BaseAgent(
            system_prompt="test",
            json_schema={"type": "object"},
            model="sonnet",
        )
        stdout = make_cli_response({"ok": True})

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            await agent.invoke("test prompt")

            args = mock_exec.call_args[0]
            assert "--bare" in args
            assert "--allowedTools" not in args

    @pytest.mark.asyncio
    async def test_tool_mode_includes_system_prompt_in_user_prompt(self):
        """In tool mode, system prompt is prepended to user prompt (no --system-prompt flag)."""
        agent = BaseAgent(
            system_prompt="You are a helpful assistant.",
            json_schema={"type": "object"},
            model="sonnet",
            allowed_tools=["StructuredOutput"],
        )
        stdout = make_cli_response({"ok": True})

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 0
            mock_exec.return_value = proc

            await agent.invoke("analyze this")

            args = mock_exec.call_args[0]
            # --system-prompt not used in tool mode
            assert "--system-prompt" not in args
            # User prompt should contain both system prompt and user message
            prompt_idx = list(args).index("-p") + 1
            prompt = args[prompt_idx]
            assert "helpful assistant" in prompt
            assert "analyze this" in prompt


class TestBaseAgentBatch:
    @pytest.mark.asyncio
    async def test_invoke_batch_parallel(self):
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
            model="haiku",
        )

        call_count = 0

        async def mock_exec(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            proc = AsyncMock()
            proc.communicate.return_value = (
                make_cli_response({"n": call_count}), b""
            )
            proc.returncode = 0
            return proc

        with patch("polily.agents.base.asyncio.create_subprocess_exec", side_effect=mock_exec):
            results = await agent.invoke_batch(
                ["prompt1", "prompt2", "prompt3"],
                max_concurrent=2,
            )

        assert len(results) == 3
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_invoke_batch_fallback_on_partial_failure(self):
        """If one call fails with fallback, others should still succeed."""
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="haiku",
            fallback_fn=lambda p: {"fallback": True},
        )

        async def mock_exec(*args, **kwargs):
            # Check if prompt contains "b" as the original input — always fail for it
            prompt_arg = args[2] if len(args) > 2 else ""
            proc = AsyncMock()
            if prompt_arg.startswith("b\n") or prompt_arg == "b":
                proc.communicate.return_value = (b"", b"error")
                proc.returncode = 1
            else:
                proc.communicate.return_value = (
                    make_cli_response({"ok": True}), b""
                )
                proc.returncode = 0
            return proc

        with patch("polily.agents.base.asyncio.create_subprocess_exec", side_effect=mock_exec):
            results = await agent.invoke_batch(["a", "b", "c"], max_concurrent=3)

        assert len(results) == 3
        assert results[1] == {"fallback": True}
