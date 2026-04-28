"""LLM language directive: NarrativeWriterAgent prepends a per-language
instruction so the LLM responds in the user's UI language."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.tui import i18n


@pytest.fixture(autouse=True)
def _restore_i18n():
    yield
    from polily.tui.i18n import _BUNDLED_CATALOGS_DIR
    bundled = i18n.load_catalogs(_BUNDLED_CATALOGS_DIR)
    i18n.init_i18n(bundled, default="zh")


def _make_agent() -> NarrativeWriterAgent:
    cfg = MagicMock()
    cfg.model = "sonnet"
    cfg.timeout_seconds = 300
    cfg.max_prompt_chars = 8000
    return NarrativeWriterAgent(cfg)


def test_zh_directive_prepended():
    agent = _make_agent()
    prompt = agent._build_prompt("event-1", has_position=False)
    # zh directive: explicit Chinese requirement
    assert "简体中文" in prompt
    assert "回答语言要求" in prompt
    # Directive should appear BEFORE the analysis instructions so the
    # LLM sees it first.
    assert prompt.index("简体中文") < prompt.index("分析事件")


def test_en_directive_prepended():
    i18n.set_language("en")
    agent = _make_agent()
    prompt = agent._build_prompt("event-1", has_position=False)
    assert "Respond in English" in prompt
    assert "Response language requirement" in prompt
    # The Chinese-coded scaffolding (mode/数据库/etc.) stays — directive
    # tells the LLM how to write the OUTPUT, not how the prompt itself
    # is phrased.
    assert "分析事件" in prompt


def test_directive_present_for_position_management_mode():
    """Directive must apply to position-management calls too — those are
    the ones that produce P&L narratives users read most often."""
    i18n.set_language("en")
    agent = _make_agent()
    prompt = agent._build_prompt(
        "event-1", has_position=True, position_summary="YES 50 shares @ 0.42",
    )
    assert "Respond in English" in prompt
    assert "持仓" in prompt  # Chinese scaffolding still there
