"""Read MCP server configuration from the Claude CLI's user-scope config.

Background: polily's NarrativeWriter agent invokes `claude -p` with an
`--allowedTools` allowlist. To let the agent call MCP server tools (e.g.,
`mcp__blockbeats__get_newsflash`), polily must enumerate each configured
MCP server's name in that allowlist. The Claude CLI does NOT honor a
top-level `mcp__*` glob — only per-server wildcards (`mcp__<name>__*`)
work. (Verified by POC, 2026-05-24.)

This module reads the list of configured server names from
`~/.claude.json` (the Claude CLI's user-scope config file). Callers then
build `mcp__<name>__*` allowlist entries from the returned names.

Design choices:
- **Fail-open.** Any read / parse error returns `[]`. The base allowlist
  (Read, Bash, Grep, WebSearch, TodoWrite) still works; the agent just
  can't call MCP tools when polily can't discover them. This is strictly
  better than throwing on agent startup.
- **`POLILY_CLAUDE_CONFIG` env var override.** If Claude CLI ever moves
  its config file in a future version, users can point polily at the
  new path without a polily code change.
- **Pure.** No side effects beyond reading the file (no logging, no
  network, no DB).
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def list_user_mcp_servers() -> list[str]:
    """Return the names of MCP servers configured at the user's Claude CLI level.

    Reads `~/.claude.json` (or `$POLILY_CLAUDE_CONFIG` if set), extracts the
    `mcpServers` dict's keys, and returns them as a list.

    Returns an empty list on any error (file missing, malformed JSON,
    no `mcpServers` key, unreadable file, etc.) — see module docstring
    for the fail-open rationale.

    Example:
        >>> # With ~/.claude.json containing:
        >>> # {"mcpServers": {"blockbeats": {...}, "tree_news": {...}}}
        >>> list_user_mcp_servers()
        ['blockbeats', 'tree_news']
    """
    path = Path(os.environ.get("POLILY_CLAUDE_CONFIG", "~/.claude.json")).expanduser()
    try:
        cfg = json.loads(path.read_text())
    except (FileNotFoundError, PermissionError, json.JSONDecodeError, OSError, ValueError):
        return []
    mcp_servers = cfg.get("mcpServers", {}) if isinstance(cfg, dict) else {}
    if not isinstance(mcp_servers, dict):
        return []
    return list(mcp_servers.keys())
