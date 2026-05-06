"""AF-1 (v0.11.7): rendering and integration tests for the frozen
prices YAML block.

The structural fix for the AF-1 bug (event 57711 v5 cross-paragraph
price disagreement) lives in Tasks 6-8: capture prices BEFORE the
agent runs, render them in the prompt YAML block, delete the markets
sqlite3 templates that let the agent re-query. The actual SQLite-level
concurrency safety is structurally guaranteed by removing the query
path entirely — Task 11's grep invariant fences off regression.

This test file covers:
- Helper rendering correctness (YAML shape, None handling, empty input)
- Snapshot-decoupling semantic (once rendered, the string is immutable)
- _build_prompt integration (YAML block prepends to template body when
  frozen_prices is provided; backward-compat preserved when not)
"""
from __future__ import annotations

import pytest

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.core.config import AgentConfig


@pytest.fixture
def agent():
    """A NarrativeWriterAgent instance — only used for _build_prompt
    and _render_frozen_prices_section static methods, no actual claude
    CLI invocation."""
    return NarrativeWriterAgent(AgentConfig())


def test_render_frozen_prices_section_yaml_block(agent):
    """Renders the YAML block correctly with multiple markets."""
    frozen = {
        "m1": {"yes": 0.55, "no": 0.45},
        "m2": {"yes": 0.32, "no": 0.68},
    }
    section = agent._render_frozen_prices_section(frozen)

    assert "prices_snapshot_at:" in section
    assert "markets:" in section
    assert "m1: {yes: 0.5500, no: 0.4500}" in section
    assert "m2: {yes: 0.3200, no: 0.6800}" in section
    assert "## 价格快照" in section


def test_render_frozen_prices_section_empty_returns_empty(agent):
    """No frozen_prices → empty string (legacy fallback path)."""
    assert agent._render_frozen_prices_section(None) == ""
    assert agent._render_frozen_prices_section({}) == ""


def test_render_frozen_prices_section_handles_none_price(agent):
    """A market with yes=None / no=None renders as 'null' instead of crashing."""
    frozen = {"m1": {"yes": 0.55, "no": None}}
    section = agent._render_frozen_prices_section(frozen)
    assert "no: null" in section


def test_render_frozen_prices_section_uses_injected_captured_at(agent):
    """Whis-review SG-2: captured_at is an explicit param so tests can
    pass deterministic timestamps. Production callers leave it None."""
    frozen = {"m1": {"yes": 0.55, "no": 0.45}}
    section = agent._render_frozen_prices_section(
        frozen, captured_at="2026-05-07T12:00:00+00:00",
    )
    assert "prices_snapshot_at: 2026-05-07T12:00:00+00:00" in section


def test_captured_snapshot_decouples_from_source(agent):
    """Documenting the snapshot semantic: once `_render_frozen_prices_section`
    consumes a dict, mutations to the source dict do not affect the
    rendered string (because the renderer iterated and produced a string
    that's now immutable).

    This is the property `service.py` relies on: it builds prices_snapshot
    once at agent-call-time, threads it down. The agent's prompt body is
    now a string — it cannot be mutated by a later daemon poll-job
    write. This test shows the property at the helper level.

    NOT a SQLite-level concurrency test — that's structurally guaranteed
    by Tasks 6-8 (no `FROM markets` query from prompt → no race possible).
    Task 11 grep invariant fences off the structural fix.
    """
    frozen = {"m1": {"yes": 0.55, "no": 0.45}}
    section_v1 = agent._render_frozen_prices_section(
        frozen, captured_at="2026-05-07T12:00:00+00:00",
    )

    # Mutate the source dict.
    frozen["m1"]["yes"] = 0.99
    frozen["m1"]["no"] = 0.01

    # Re-render — the new render reflects the new mutation (because we
    # passed the live dict). This is by design: callers responsible for
    # passing a stable snapshot. service.py builds a fresh dict via
    # comprehension, then doesn't mutate it.
    section_v2 = agent._render_frozen_prices_section(
        frozen, captured_at="2026-05-07T12:00:00+00:00",
    )

    # Original rendered string is unchanged — strings are immutable.
    assert "yes: 0.5500" in section_v1
    assert "yes: 0.9900" not in section_v1

    # New render shows new value (caller's responsibility to capture once).
    assert "yes: 0.9900" in section_v2

    # The two renders are different strings (proving render is pure).
    assert section_v1 != section_v2


def test_build_prompt_with_frozen_prices_prepends_yaml_block(agent):
    """Integration: _build_prompt prepends the YAML block when
    frozen_prices is provided."""
    frozen = {"m1": {"yes": 0.55, "no": 0.45}}

    prompt = agent._build_prompt(
        event_id="evt1",
        has_position=False,
        position_summary="",
        frozen_prices=frozen,
    )

    # Block at the top — the YAML markers must come before the rest of
    # the template body.
    yaml_marker_pos = prompt.find("prices_snapshot_at:")
    assert yaml_marker_pos != -1
    # Must precede the body (the language directive / "分析事件" line).
    body_marker_pos = prompt.find("分析事件")
    if body_marker_pos != -1:
        assert yaml_marker_pos < body_marker_pos


def test_build_prompt_without_frozen_prices_legacy_unchanged(agent):
    """When frozen_prices is None, the prompt is unchanged from the
    template — preserves backward compat for unit tests of
    _build_prompt that don't supply frozen_prices."""
    prompt_no_frozen = agent._build_prompt(
        event_id="evt1",
        has_position=False,
        position_summary="",
    )
    prompt_explicit_none = agent._build_prompt(
        event_id="evt1",
        has_position=False,
        position_summary="",
        frozen_prices=None,
    )
    assert prompt_no_frozen == prompt_explicit_none
    assert "prices_snapshot_at:" not in prompt_no_frozen
