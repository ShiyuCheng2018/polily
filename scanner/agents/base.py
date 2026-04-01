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

# Debug log directory
_DEBUG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data")


def _dump_debug(tag: str, content: str):
    """Write debug info to data/agent_debug.log (append). Always writes, no log level."""
    try:
        from datetime import UTC, datetime
        ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        path = os.path.join(_DEBUG_DIR, "agent_debug.log")
        with open(path, "a") as f:
            f.write(f"\n=== {tag} [{ts}] ===\n{content}\n")
    except Exception:
        pass


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

    Heartbeat monitoring: emits status callbacks during long-running calls.
    No system kill — user decides when to cancel via cancel().
    """

    def __init__(
        self,
        system_prompt: str,
        json_schema: dict,
        model: str = "sonnet",
        cli_command: str = "claude",
        fallback_fn: Callable[[str], dict] | None = None,
        max_prompt_chars: int = DEFAULT_MAX_PROMPT_CHARS,
        # Legacy compat — these are ignored now (no system kill)
        idle_timeout_seconds: float = 0,
        timeout_seconds: float | None = None,
    ):
        self.system_prompt = system_prompt
        self.json_schema = json_schema
        self.model = model
        self.cli_command = cli_command
        self.fallback_fn = fallback_fn
        self.max_prompt_chars = max_prompt_chars
        self._current_proc: asyncio.subprocess.Process | None = None
        self._cancelled = False

    def cancel(self):
        """Cancel the currently running CLI call. Safe to call from any thread."""
        self._cancelled = True
        proc = self._current_proc
        if proc and proc.returncode is None:
            try:
                proc.kill()
                logger.info("Cancelled agent subprocess %d", proc.pid)
            except (ProcessLookupError, PermissionError):
                pass

    async def invoke(
        self, prompt: str, max_retries: int = 2,
        on_heartbeat: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Call claude CLI and return parsed JSON dict.

        on_heartbeat(elapsed_seconds, status): called every ~5s during execution.
          status: "running" (<60s), "slow" (60-120s), "unresponsive" (>120s)
        """
        self._cancelled = False
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
                    result = await self._call_cli(actual_prompt, on_heartbeat)
                    return result
                except Exception as e:
                    if self._cancelled:
                        raise RuntimeError("Agent cancelled by user") from e
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

    async def _call_cli(
        self, prompt: str,
        on_heartbeat: Callable[[float, str], None] | None = None,
    ) -> dict:
        """Execute claude CLI with heartbeat monitoring.

        No system kill — runs until process completes or cancel() is called.
        Emits heartbeat status via on_heartbeat callback every ~5 seconds.
        """
        import time

        args = [
            self.cli_command, "-p", prompt,
            "--output-format", "json",
            "--json-schema", json.dumps(self.json_schema),
            "--system-prompt", self.system_prompt,
            "--model", self.model,
        ]

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._current_proc = proc
        _active_pids.add(proc.pid)

        try:
            comm_task = asyncio.ensure_future(proc.communicate())
            start = time.monotonic()
            while not comm_task.done():
                await asyncio.sleep(5.0)
                elapsed = time.monotonic() - start
                # Emit heartbeat status
                if on_heartbeat:
                    if elapsed > 120:
                        on_heartbeat(elapsed, "unresponsive")
                    elif elapsed > 60:
                        on_heartbeat(elapsed, "slow")
                    else:
                        on_heartbeat(elapsed, "running")
                logger.debug("Agent still running (%.0fs)...", elapsed)

            stdout, stderr = comm_task.result()
        finally:
            self._current_proc = None
            _active_pids.discard(proc.pid)
            if proc.returncode is None:
                proc.kill()
                await proc.wait()

        if proc.returncode != 0:
            err_text = stderr.decode()[:500]
            _dump_debug("cli_error", f"exit={proc.returncode}\n{err_text}\n---stdout---\n{stdout.decode()[:2000]}")
            raise RuntimeError(f"claude CLI exited with code {proc.returncode}: {err_text}")

        raw_output = stdout.decode()
        _dump_debug("cli_stdout", raw_output)
        try:
            return self._parse_response(raw_output)
        except Exception as e:
            _dump_debug("parse_error", f"{e}\n---\n{raw_output}")
            raise

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
