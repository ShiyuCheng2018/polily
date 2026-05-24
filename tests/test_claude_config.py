"""Tests for polily.util.claude_config.list_user_mcp_servers().

Background: polily's NarrativeWriter passes `--allowedTools` to `claude -p`.
To let the agent invoke MCP server tools (e.g., `mcp__blockbeats__*`), polily
must enumerate each configured MCP server's name in that allowlist. The Claude
CLI does NOT honor a top-level `mcp__*` glob (verified by POC 2026-05-24); only
per-server wildcards work.

`list_user_mcp_servers()` reads `~/.claude.json` (the Claude CLI's user-scope
config) and returns the configured server names. polily then builds
`mcp__<name>__*` entries from this list.

Contract:
- Fail-open: any read / parse error returns [] (polily's base allowlist still
  works, agent just can't call MCP tools).
- `POLILY_CLAUDE_CONFIG` env var overrides the default path (escape hatch if
  Claude CLI ever moves its config file).
- Pure function: no side effects beyond reading the file.
"""
from __future__ import annotations

import json

from polily.util.claude_config import list_user_mcp_servers


def test_missing_file_returns_empty(monkeypatch, tmp_path):
    """When config file doesn't exist, fail open with [] (don't raise)."""
    nonexistent = tmp_path / "no-such-file.json"
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(nonexistent))
    assert list_user_mcp_servers() == []


def test_malformed_json_returns_empty(monkeypatch, tmp_path):
    """When config file is unparseable JSON, fail open with []."""
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json")
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(bad))
    assert list_user_mcp_servers() == []


def test_no_mcpservers_key_returns_empty(monkeypatch, tmp_path):
    """When config file exists but has no `mcpServers` key, return []."""
    cfg = tmp_path / "no-mcp.json"
    cfg.write_text(json.dumps({"someOtherKey": "value", "numShellIntegrationInstalls": 1}))
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(cfg))
    assert list_user_mcp_servers() == []


def test_empty_mcpservers_returns_empty(monkeypatch, tmp_path):
    """When `mcpServers` exists but is empty dict, return []."""
    cfg = tmp_path / "empty-mcp.json"
    cfg.write_text(json.dumps({"mcpServers": {}}))
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(cfg))
    assert list_user_mcp_servers() == []


def test_returns_server_names(monkeypatch, tmp_path):
    """Happy path: each configured MCP server's name is in the returned list."""
    cfg = tmp_path / "claude.json"
    cfg.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "blockbeats": {
                        "command": "npx",
                        "args": ["-y", "blockbeats-mcp"],
                        "env": {"BLOCKBEATS_API_KEY": "test_key"},
                    },
                    "tree_news": {"command": "tree-news"},
                }
            }
        )
    )
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(cfg))
    result = list_user_mcp_servers()
    # Set comparison because dict iteration order isn't part of the contract.
    assert set(result) == {"blockbeats", "tree_news"}
    assert len(result) == 2


def test_env_var_overrides_default_path(monkeypatch, tmp_path):
    """POLILY_CLAUDE_CONFIG env var redirects the read to an alternate file.

    Documented escape hatch in the plan: if Claude CLI ever moves its config
    location, users can point polily at the new path without code changes.
    """
    alt = tmp_path / "alternate-location.json"
    alt.write_text(json.dumps({"mcpServers": {"my_custom_server": {}}}))
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(alt))
    result = list_user_mcp_servers()
    assert result == ["my_custom_server"]


def test_unreadable_file_returns_empty(monkeypatch, tmp_path):
    """When file exists but can't be read (permission error), fail open with [].

    We can't reliably create a 0-permission file in the test sandbox on macOS
    without root, so instead simulate by pointing at a directory (read returns
    IsADirectoryError, which is an OSError subclass → caught by the except).
    """
    a_dir = tmp_path / "not-a-file"
    a_dir.mkdir()
    monkeypatch.setenv("POLILY_CLAUDE_CONFIG", str(a_dir))
    assert list_user_mcp_servers() == []
