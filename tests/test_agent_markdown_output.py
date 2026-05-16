"""AgentMarkdownOutput — v0.12.0 agent output schema (replaces NarrativeWriterOutput)."""

import pytest

from polily.agents.schemas import AgentMarkdownOutput


def test_minimum_valid_output():
    out = AgentMarkdownOutput(
        markdown_body="# Edge assessment\n\nLong enough body content.",
        next_check_at="2026-05-10T13:00:00+00:00",
        next_check_reason="standard cadence",
    )
    assert out.urgency == "normal"  # default
    assert out.dev_feedback == ""   # default
    assert out.semantic_errors() == []


def test_short_body_yields_semantic_error():
    out = AgentMarkdownOutput(
        markdown_body="x",
        next_check_at="2026-05-10T13:00:00+00:00",
        next_check_reason="r",
    )
    errs = out.semantic_errors()
    assert any("markdown_body too short" in e for e in errs)


def test_missing_next_check_at_yields_semantic_error():
    out = AgentMarkdownOutput(
        markdown_body="# Long enough body content here.",
        next_check_at="",
        next_check_reason="r",
    )
    errs = out.semantic_errors()
    assert any("next_check_at is required" in e for e in errs)


def test_urgency_validates_enum():
    with pytest.raises(ValueError):
        AgentMarkdownOutput(
            markdown_body="# Long enough body content here.",
            next_check_at="2026-05-10T13:00:00+00:00",
            next_check_reason="r",
            urgency="explosive",  # not in enum
        )


def test_extra_fields_ignored():
    """Pydantic config: extra='ignore' so unknown frontmatter fields don't blow up."""
    out = AgentMarkdownOutput(
        markdown_body="# Long enough body content here.",
        next_check_at="2026-05-10T13:00:00+00:00",
        next_check_reason="r",
        unknown_field="garbage",
    )
    assert not hasattr(out, "unknown_field")
