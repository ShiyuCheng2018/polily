"""BaseAgent: invoke claude CLI in headless mode with structured output."""

import asyncio
import contextlib
import json
import logging
import os
import re
import tempfile
from collections.abc import Callable

logger = logging.getLogger(__name__)

DEFAULT_MAX_PROMPT_CHARS = 5000

# Global registry of active subprocess PIDs for cleanup on exit
_active_pids: set[int] = set()


def kill_all_agents():
    """Kill all active claude CLI subprocesses."""
    for pid in list(_active_pids):
        try:
            os.kill(pid, 9)  # SIGKILL
            logger.info("Killed agent subprocess %d", pid)
        except (ProcessLookupError, PermissionError):
            pass
    _active_pids.clear()


class BaseAgent:
    """Base class for AI agents that call claude CLI.

    Uses `claude -p` and parses JSON from the response text.
    Falls back to fallback_fn on any error if provided.
    """

    def __init__(
        self,
        system_prompt: str,
        json_schema: dict,
        model: str = "sonnet",
        cli_command: str = "claude",
        fallback_fn: Callable[[str], dict] | None = None,
        idle_timeout_seconds: float = 120,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        # Legacy: timeout_seconds still accepted but mapped to idle_timeout
        timeout_seconds: float | None = None,
    ):
        self.system_prompt = system_prompt
        self.json_schema = json_schema
        self.model = model
        self.cli_command = cli_command
        self.fallback_fn = fallback_fn
        self.idle_timeout = timeout_seconds or idle_timeout_seconds
        self.max_prompt_chars = max_prompt_chars

    async def invoke(self, prompt: str, max_retries: int = 2) -> dict:
        """Call claude CLI and return parsed JSON dict. Retries on failure."""
        tmp_path = None
        try:
            if len(prompt) > self.max_prompt_chars:
                tmp_path = self._write_temp(prompt)
                actual_prompt = f"Analyze the data in file: {tmp_path}"
            else:
                actual_prompt = prompt

            last_error = None
            for attempt in range(1, max_retries + 1):
                try:
                    result = await self._call_cli(actual_prompt)
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_retries:
                        wait = attempt * 3
                        logger.warning("Agent attempt %d/%d failed: %s. Retrying in %ds...", attempt, max_retries, e, wait)
                        await asyncio.sleep(wait)
                    else:
                        logger.warning("Agent failed after %d attempts: %s", max_retries, e)

            if self.fallback_fn:
                return self.fallback_fn(prompt)
            raise last_error
        finally:
            if tmp_path:
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)

    async def invoke_batch(
        self, prompts: list[str], max_concurrent: int = 3
    ) -> list[dict]:
        """Run multiple prompts in parallel with concurrency limit."""
        sem = asyncio.Semaphore(max_concurrent)

        async def bounded(p: str) -> dict:
            async with sem:
                return await self.invoke(p)

        return await asyncio.gather(*[bounded(p) for p in prompts])

    async def _call_cli(self, prompt: str) -> dict:
        """Execute claude CLI with heartbeat-based idle detection.

        Instead of a hard timeout, polls the process periodically and only
        kills it if it hasn't finished within idle_timeout seconds of the
        last check. This allows agents doing web searches to take as long
        as needed while still catching stuck processes.
        """
        import time

        props = self.json_schema.get("properties", {})
        fields = list(props.keys())[:10]
        full_prompt = (
            f"{prompt}\n\n"
            f"返回 JSON 格式，包含以下字段: {', '.join(fields)}。只返回 JSON，不要其他内容。"
        )

        args = [
            self.cli_command, "-p", full_prompt,
            "--output-format", "json",
            "--system-prompt", self.system_prompt,
            "--model", self.model,
        ]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _active_pids.add(proc.pid)

        try:
            # Wrap communicate() as a task, poll for idle timeout
            comm_task = asyncio.ensure_future(proc.communicate())
            start = time.monotonic()
            while not comm_task.done():
                await asyncio.sleep(5.0)
                elapsed = time.monotonic() - start
                if elapsed > self.idle_timeout:
                    comm_task.cancel()
                    proc.kill()
                    await proc.wait()
                    raise RuntimeError(
                        f"claude CLI not responding after {self.idle_timeout:.0f}s, killed"
                    )
                logger.debug("Agent still running (%.0fs)...", elapsed)

            stdout, stderr = comm_task.result()
        finally:
            _active_pids.discard(proc.pid)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

        if proc.returncode != 0:
            raise RuntimeError(f"claude CLI exited with code {proc.returncode}: {stderr.decode()[:500]}")

        return self._parse_response(stdout.decode())

    def _parse_response(self, raw_output: str) -> dict:
        """Parse JSON from claude CLI output. Handles multiple response formats."""
        # Try 1: Parse as claude CLI JSON envelope ({"type":"result", "result":"..."})
        try:
            envelope = json.loads(raw_output)
            if isinstance(envelope, dict):
                # Check for structured_output first (if --json-schema worked)
                if "structured_output" in envelope and envelope["structured_output"]:
                    return envelope["structured_output"]
                # Extract result text and parse JSON from it
                result_text = envelope.get("result", "")
                if isinstance(result_text, dict):
                    return result_text
                if isinstance(result_text, str):
                    return self._extract_json_from_text(result_text)
        except json.JSONDecodeError:
            pass

        # Try 2: Raw output might be JSON directly
        try:
            parsed = json.loads(raw_output)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Try 3: Extract JSON from text (might have markdown fences)
        return self._extract_json_from_text(raw_output)

    def _extract_json_from_text(self, text: str) -> dict:
        """Extract JSON object from text that may contain markdown fences or other text."""
        # Try to find JSON in code blocks
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find raw JSON object
        brace_match = re.search(r'\{[\s\S]*\}', text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        raise RuntimeError(f"No JSON found in claude CLI response: {text[:200]}")

    def _write_temp(self, content: str) -> str:
        """Write content to a temp file and return its path."""
        fd, path = tempfile.mkstemp(suffix=".txt", prefix="polily_agent_")
        with os.fdopen(fd, "w") as f:
            f.write(content)
        return path
