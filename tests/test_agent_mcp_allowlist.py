"""Tests for `_build_agent_tools()` — composes NarrativeWriter's --allowedTools.

Background: see `tests/test_claude_config.py` and
`docs/internal/plans/2026-05-24-agent-tools-mcp-allowlist.md`.

The function reads MCP server names from the user's Claude CLI config
(via `list_user_mcp_servers`) and appends `mcp__<name>__*` entries to a
fixed base allowlist. This test isolates the composition logic by stubbing
`list_user_mcp_servers` rather than touching `~/.claude.json`.
"""
from __future__ import annotations

from polily.agents.narrative_writer import _BASE_AGENT_TOOLS, _build_agent_tools


def test_no_mcp_servers_returns_base(monkeypatch):
    """When the user has no MCP servers configured, the allowlist equals
    the base — no `mcp__*` entries appended. This is the default behavior
    for users who never ran `claude mcp add`.
    """
    monkeypatch.setattr(
        "polily.agents.narrative_writer.list_user_mcp_servers",
        lambda: [],
    )
    assert _build_agent_tools() == _BASE_AGENT_TOOLS


def test_one_mcp_server_appends_wildcard(monkeypatch):
    """With one MCP server configured, exactly one `mcp__<name>__*` is
    appended in order after the base tools.
    """
    monkeypatch.setattr(
        "polily.agents.narrative_writer.list_user_mcp_servers",
        lambda: ["blockbeats"],
    )
    result = _build_agent_tools()
    assert result == _BASE_AGENT_TOOLS + ["mcp__blockbeats__*"]


def test_multiple_mcp_servers_each_get_wildcard(monkeypatch):
    """Every configured MCP server contributes its own `mcp__<name>__*`
    entry. The order matches `list_user_mcp_servers()` output (which is
    dict-iteration order on the underlying JSON).
    """
    monkeypatch.setattr(
        "polily.agents.narrative_writer.list_user_mcp_servers",
        lambda: ["blockbeats", "tree_news", "custom_server"],
    )
    result = _build_agent_tools()
    assert result == _BASE_AGENT_TOOLS + [
        "mcp__blockbeats__*",
        "mcp__tree_news__*",
        "mcp__custom_server__*",
    ]


def test_base_tools_unchanged_when_servers_present(monkeypatch):
    """Defensive: the base tool list (Read, Bash, Grep, WebSearch, TodoWrite)
    must still be intact in the output — we ADD to it, never REPLACE.
    """
    monkeypatch.setattr(
        "polily.agents.narrative_writer.list_user_mcp_servers",
        lambda: ["blockbeats"],
    )
    result = _build_agent_tools()
    # Base tools appear first, in original order, untouched.
    assert result[: len(_BASE_AGENT_TOOLS)] == _BASE_AGENT_TOOLS


def test_base_tools_constant_matches_pre_refactor_value():
    """Regression guard: `_BASE_AGENT_TOOLS` must remain the v0.12.x stable
    set. If this needs to change (e.g., dropping WebSearch), it's an
    intentional API decision, not an incidental refactor.
    """
    assert _BASE_AGENT_TOOLS == ["Read", "Bash", "Grep", "WebSearch", "TodoWrite"]
