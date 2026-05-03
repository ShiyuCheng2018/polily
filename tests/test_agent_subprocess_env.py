"""v0.11.0 — claude subprocess inherits POLILY_DB env var so the
agent prompt's `sqlite3 "$POLILY_DB" ...` resolves to the resolved
DB path regardless of cwd / install path.

Pre-fix: BaseAgent._call_cli invoked claude via
asyncio.create_subprocess_exec WITHOUT an env= kwarg, so the
subprocess inherited the parent env unmodified — POLILY_DB was
never set, and the prompt's sqlite3 invocations relied on cwd
matching the user's repo root.

Post-fix: pass env=os.environ.copy() with POLILY_DB injected.

Whis-review S10: real BaseAgent subprocess method is `_call_cli`
(NOT `_invoke_claude` as the plan's first draft suggested).
"""
from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock, MagicMock

import pytest

from polily.agents.base import BaseAgent
from polily.core import paths


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.delenv("POLILY_DATA_DIR", raising=False)
    monkeypatch.delenv("POLILY_LOG_DIR", raising=False)
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)
    monkeypatch.setenv("POLILY_DATA_DIR", str(tmp_path / "polily_data"))
    yield
    paths.set_data_dir_override(None)
    paths.set_log_dir_override(None)


@pytest.mark.asyncio
async def test_claude_subprocess_receives_polily_db_env(monkeypatch, tmp_path):
    """When BaseAgent invokes claude CLI, it sets POLILY_DB in subprocess env
    so the prompt's `sqlite3 "$POLILY_DB"` references the resolved path."""
    captured_kwargs: dict = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_kwargs.update(kwargs)
        proc = MagicMock()
        proc.communicate = AsyncMock(
            return_value=(b'[{"type":"result","result":"{}"}]', b"")
        )
        proc.returncode = 0
        proc.pid = 12345
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    agent = BaseAgent(
        system_prompt="test system prompt",
        json_schema={"type": "object"},
        model="haiku",
        max_prompt_chars=5000,
    )
    # The fake returns "{}" so parsing might raise — irrelevant; we
    # only assert on env propagation to the subprocess.
    with contextlib.suppress(Exception):
        await agent._call_cli("test prompt")

    env = captured_kwargs.get("env")
    assert env is not None, (
        "BaseAgent._call_cli did not pass env= to create_subprocess_exec; "
        "subprocess will inherit parent env without POLILY_DB injection."
    )
    assert "POLILY_DB" in env, (
        f"POLILY_DB missing from subprocess env: {sorted(env.keys())[:20]}..."
    )
    assert env["POLILY_DB"] == str(paths.db_path()), (
        f"POLILY_DB={env['POLILY_DB']!r} does not match paths.db_path()={paths.db_path()!r}"
    )


@pytest.mark.asyncio
async def test_claude_subprocess_inherits_parent_env(monkeypatch, tmp_path):
    """The env passed to the subprocess MUST be a copy of os.environ
    (not just {"POLILY_DB": ...}). Without parent-env inheritance,
    `claude` cannot resolve HOME for ~/.claude config lookup, PATH
    for binary resolution, or POLILY_CLAUDE_CLI for the daemon-set
    CLI path.
    """
    monkeypatch.setenv("POLILY_TEST_MARKER", "marker_value_xyz")

    captured_kwargs: dict = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured_kwargs.update(kwargs)
        proc = MagicMock()
        proc.communicate = AsyncMock(
            return_value=(b'[{"type":"result","result":"{}"}]', b"")
        )
        proc.returncode = 0
        proc.pid = 12345
        return proc

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    agent = BaseAgent(
        system_prompt="test",
        json_schema={"type": "object"},
        model="haiku",
        max_prompt_chars=5000,
    )
    with contextlib.suppress(Exception):
        await agent._call_cli("test prompt")

    env = captured_kwargs.get("env")
    assert env is not None
    # Parent env propagated:
    assert env.get("POLILY_TEST_MARKER") == "marker_value_xyz", (
        "Subprocess env does not inherit parent env — must use os.environ.copy(), "
        "not a dict with only POLILY_DB."
    )
    # POLILY_DB still added:
    assert env.get("POLILY_DB") == str(paths.db_path())
