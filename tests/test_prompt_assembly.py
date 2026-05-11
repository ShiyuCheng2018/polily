"""Verify v0.12.0 prompt assembly produces 4-part structure."""
from pathlib import Path

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB
from polily.core.strategy_store import save_user_strategy, set_active_strategy


def _make_agent() -> NarrativeWriterAgent:
    cfg = AgentConfig()  # default config; tests don't actually call claude CLI
    return NarrativeWriterAgent(cfg)


def _build_prompt(db, event_id, has_position, position_summary, trigger_source):
    nw = _make_agent()
    return nw._build_prompt(
        event_id=event_id,
        has_position=has_position,
        position_summary=position_summary,
        db=db,
        trigger_source=trigger_source,
    )


def test_prompt_contains_per_call_ephemeral_block(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "manual")
    assert "event_id: evt1" in prompt
    assert "trigger: manual" in prompt
    assert "has_position: false" in prompt
    assert "official_strategy_path:" in prompt
    assert "language_directive" in prompt or "Language" in prompt or "language." in prompt


def test_prompt_contains_position_summary_when_has_position(tmp_path):
    """position_summary is preserved as a raw fact in the per-call block."""
    db = PolilyDB(tmp_path / "polily.db")
    summary = "YES @ 0.42, qty 100, cost basis 0.38"
    prompt = _build_prompt(db, "evt1", True, summary, "manual")
    assert "has_position: true" in prompt
    assert summary in prompt


def test_prompt_contains_manual_md(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "scan")
    assert "## 1. Who You Are" in prompt
    assert "## 7. Per-Call Inputs" in prompt


def test_prompt_contains_official_strategy_when_active_official(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    set_active_strategy(db, "official")
    prompt = _build_prompt(db, "evt1", True, "long YES @0.42", "movement")
    assert "Polily Default Analysis Strategy" in prompt


def test_prompt_contains_user_strategy_when_active_user(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    save_user_strategy(db, "# My Strategy\n\nDo X then Y.")
    set_active_strategy(db, "user")
    prompt = _build_prompt(db, "evt1", False, None, "scan")
    assert "# My Strategy" in prompt
    assert "Do X then Y." in prompt


def test_prompt_contains_protocol_footer(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "scan")
    assert "Output Protocol" in prompt
    assert "next_check_at" in prompt
    # protocol.md uses markdown bolding for emphasis: "**MUST be present**"
    assert "frontmatter" in prompt
    assert "MUST be present" in prompt


def test_protocol_requires_dev_feedback_score_prefix(tmp_path):
    """v0.12.0 hotfix: dev_feedback must start with `[N/10]` score prefix.

    v0.11.x dev_feedback always carried this score (10 = polily nailed
    everything for this analysis; 1 = major data/prompt/platform issues).
    The score gives maintainers a one-glance scannable signal — log
    aggregation can sort by score and surface the lowest-rated entries
    first. The v0.12.0 markdown migration lost this discipline; all
    current production entries are score-less prose.
    """
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "manual")
    # Protocol must explicitly call out the [N/10] prefix
    assert "[N/10]" in prompt or "[n/10]" in prompt.lower(), (
        "protocol.md must require dev_feedback to start with a [N/10] score "
        "prefix (e.g. [8/10] short observation...). Without this, all "
        "feedback entries are unrankable prose."
    )
    # And explain the rating semantics
    assert ("10 = " in prompt or "10 =" in prompt) and "1 = " in prompt, (
        "protocol.md must explain the 1-10 rating semantics "
        "(what high score means, what low score means)"
    )


def test_protocol_requires_next_check_reason_consistency(tmp_path):
    """v0.12.0 polish: protocol.md must instruct the agent to keep
    next_check_reason consistent with next_check_at.

    Real-world miss: Iran uranium event v1 had next_check_at = 5/12 paired
    with reason 'Iran 48hr MOU response window expires' — but the 48hr
    window had already closed on 5/9. User couldn't tell why polily
    scheduled the check there.
    """
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "manual")
    # Must mention consistency between the timestamp and the reason
    assert "consistent with" in prompt or "consistency" in prompt.lower(), (
        "protocol.md must require next_check_reason to be consistent with next_check_at"
    )


def test_prompt_assembly_order(tmp_path):
    """Order: ephemeral → manual → strategy → protocol."""
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "scan")
    ephemeral_idx = prompt.find("event_id: evt1")
    manual_idx = prompt.find("## 1. Who You Are")
    strategy_idx = prompt.find("Polily Default Analysis Strategy")
    protocol_idx = prompt.find("Output Protocol")
    assert ephemeral_idx < manual_idx < strategy_idx < protocol_idx


def test_prompt_has_official_strategy_path_pointing_to_real_file(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt1", False, None, "manual")
    for line in prompt.splitlines():
        if line.strip().startswith("official_strategy_path:"):
            path_str = line.split(":", 1)[1].strip().strip('"')
            assert Path(path_str).exists()
            assert path_str.endswith("default.md")
            return
    raise AssertionError("official_strategy_path line not found in prompt")


def test_agent_tools_no_longer_include_structured_output():
    """v0.12.0 drops StructuredOutput from allowed tools."""
    from polily.agents.narrative_writer import AGENT_TOOLS
    assert "StructuredOutput" not in AGENT_TOOLS
    assert "Read" in AGENT_TOOLS  # Read tool required for fallback path
