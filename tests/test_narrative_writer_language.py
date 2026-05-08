"""LLM language directive: NarrativeWriterAgent prepends a per-language
instruction so the LLM responds in the user's UI language.

v0.12.0: prompt is now 4-part assembled (ephemeral + manual + strategy +
protocol). The language directive is in the per-call ephemeral block,
labelled ``language_directive:``. The Chinese-coded scaffolding from
v0.11.x (`分析事件 / 持仓`) is gone — the agent now reads
manual.md / protocol.md / the active strategy.
"""
from __future__ import annotations

import pytest

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB
from polily.tui import i18n


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


def _make_agent() -> NarrativeWriterAgent:
    return NarrativeWriterAgent(AgentConfig(model="sonnet", timeout_seconds=300))


def _build(db, has_position=False, position_summary=None):
    return _make_agent()._build_prompt(
        event_id="event-1",
        has_position=has_position,
        position_summary=position_summary,
        db=db,
        trigger_source="manual",
    )


def test_zh_directive_prepended(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build(db)
    # zh directive: explicit Chinese requirement
    assert "简体中文" in prompt
    assert "回答语言要求" in prompt
    # Directive sits in the per-call ephemeral block (top of prompt),
    # which is BEFORE the static manual.md content (## 1. Who You Are).
    assert prompt.index("简体中文") < prompt.index("## 1. Who You Are")


def test_en_directive_prepended(tmp_path):
    i18n.set_language("en")
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build(db)
    assert "Respond in English" in prompt
    assert "Response language requirement" in prompt
    # Manual content (English) follows the directive — verify the
    # directive sits in the ephemeral block above the manual.
    assert prompt.index("Respond in English") < prompt.index("## 1. Who You Are")


def test_directive_present_for_position_management_mode(tmp_path):
    """Directive must apply to position-management calls too — those are
    the ones that produce P&L narratives users read most often."""
    i18n.set_language("en")
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build(db, has_position=True, position_summary="YES 50 shares @ 0.42")
    assert "Respond in English" in prompt
    # has_position=true is reflected in the ephemeral block.
    assert "has_position: true" in prompt
    # Raw position_summary is preserved as a fact (Q4: facts injected,
    # strategy interprets — no in-prompt mode abstraction).
    assert "YES 50 shares @ 0.42" in prompt
