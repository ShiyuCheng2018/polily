"""Tests for AI agent base: claude CLI invocation, JSON parsing."""

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


class TestBaseAgentErrorMessage:
    """Claude CLI emits API failures as JSON on stdout (is_error=true + api_error_status
    + result text) while stderr stays empty. The RuntimeError must carry that payload so
    users see '401 Invalid authentication credentials' in the TUI instead of an empty
    'exited with code 1:' and having to dig through agent_debug.log."""

    @pytest.mark.asyncio
    async def test_nonzero_exit_surfaces_api_error_from_stdout(self):
        """When CLI stdout has is_error=true envelope, error must include status + result."""
        import json as _json
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="sonnet",
        )
        stdout = _json.dumps({
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": 401,
            "result": (
                "Failed to authenticate. API Error: 401 "
                '{"type":"error","error":{"type":"authentication_error",'
                '"message":"Invalid authentication credentials"}}'
            ),
        }).encode()

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 1
            mock_exec.return_value = proc

            with pytest.raises(RuntimeError) as excinfo:
                await agent.invoke("test", max_retries=1)

            msg = str(excinfo.value)
            assert "401" in msg
            assert "Invalid authentication credentials" in msg

    @pytest.mark.asyncio
    async def test_nonzero_exit_surfaces_api_error_from_stdout_array(self):
        """CLI v2.1+ emits a JSON array; the result envelope is inside it."""
        import json as _json
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="sonnet",
        )
        stdout = _json.dumps([
            {"type": "system", "subtype": "init"},
            {
                "type": "result",
                "is_error": True,
                "api_error_status": 429,
                "result": "Rate limit exceeded. API Error: 429",
            },
        ]).encode()

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (stdout, b"")
            proc.returncode = 1
            mock_exec.return_value = proc

            with pytest.raises(RuntimeError) as excinfo:
                await agent.invoke("test", max_retries=1)

            msg = str(excinfo.value)
            assert "429" in msg
            assert "Rate limit" in msg

    @pytest.mark.asyncio
    async def test_nonzero_exit_falls_back_to_stderr_when_stdout_unparseable(self):
        """If stdout is not JSON, keep the current behaviour of surfacing stderr."""
        agent = BaseAgent(
            system_prompt="X",
            json_schema={"type": "object"},
            model="sonnet",
        )

        with patch("polily.agents.base.asyncio.create_subprocess_exec") as mock_exec:
            proc = AsyncMock()
            proc.communicate.return_value = (b"not json", b"command not found: claude")
            proc.returncode = 127
            mock_exec.return_value = proc

            with pytest.raises(RuntimeError) as excinfo:
                await agent.invoke("test", max_retries=1)

            msg = str(excinfo.value)
            assert "127" in msg
            assert "command not found" in msg


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


class TestBaseAgentCliCommandResolution:
    """cli_command default resolution: env var > bare 'claude'.

    Contract lets the launchd-spawned daemon (whose PATH is stripped)
    invoke the correct `claude` binary by reading POLILY_CLAUDE_CLI,
    which `generate_launchd_plist` writes into the plist at install time.
    """

    def test_reads_env_var_when_cli_command_unset(self, monkeypatch, tmp_path):
        fake = tmp_path / "claude"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setenv("POLILY_CLAUDE_CLI", str(fake))
        agent = BaseAgent(
            system_prompt="x", json_schema={"type": "object"}, model="haiku",
        )
        assert agent.cli_command == str(fake)

    def test_falls_back_to_bare_claude_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("POLILY_CLAUDE_CLI", raising=False)
        agent = BaseAgent(
            system_prompt="x", json_schema={"type": "object"}, model="haiku",
        )
        assert agent.cli_command == "claude"

    def test_dangling_env_path_falls_back_with_warning(self, monkeypatch, caplog):
        """If POLILY_CLAUDE_CLI points at a path that no longer exists
        (common after nvm removes an old node version), self-check must
        fall back to bare 'claude' AND log a user-actionable message."""
        import logging as _logging
        monkeypatch.setenv(
            "POLILY_CLAUDE_CLI", "/nonexistent/nvm/versions/node/v0.0.0/bin/claude"
        )
        with caplog.at_level(_logging.WARNING, logger="polily.agents.base"):
            agent = BaseAgent(
                system_prompt="x", json_schema={"type": "object"}, model="haiku",
            )
        assert agent.cli_command == "claude"
        assert any(
            "POLILY_CLAUDE_CLI" in rec.message
            and "polily scheduler restart" in rec.message
            for rec in caplog.records
        )

    def test_explicit_cli_command_arg_wins_over_env(self, monkeypatch, tmp_path):
        """Explicit constructor arg beats env var (back-compat for tests
        and any future caller that wants to pin a specific binary)."""
        fake = tmp_path / "claude"
        fake.write_text("#!/bin/sh\n")
        fake.chmod(0o755)
        monkeypatch.setenv("POLILY_CLAUDE_CLI", "/ignored/path")
        agent = BaseAgent(
            system_prompt="x",
            json_schema={"type": "object"},
            model="haiku",
            cli_command=str(fake),
        )
        assert agent.cli_command == str(fake)
