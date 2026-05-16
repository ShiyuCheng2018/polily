"""BaseAgent gains a 'markdown mode' (json_schema=None) for v0.12.0 free-form output."""
from polily.agents.base import BaseAgent


def test_base_agent_accepts_json_schema_none():
    """Construction with json_schema=None must not raise."""
    a = BaseAgent(
        system_prompt="you are a test agent",
        json_schema=None,
        max_prompt_chars=10000,
    )
    assert a.json_schema is None


def test_base_agent_accepts_json_schema_dict():
    """Existing construction with a schema dict still works (backward compat)."""
    a = BaseAgent(
        system_prompt="you are a test agent",
        json_schema={"type": "object", "properties": {}},
        max_prompt_chars=10000,
    )
    assert a.json_schema == {"type": "object", "properties": {}}


def test_cli_args_omit_json_schema_when_none():
    """When json_schema is None, the CLI invocation must NOT include --json-schema."""
    a = BaseAgent(
        system_prompt="test",
        json_schema=None,
        max_prompt_chars=10000,
    )
    args = a._build_cli_args(actual_prompt="hi")
    assert "--json-schema" not in args
    assert "{}" not in args  # no empty dict slipped in


def test_cli_args_include_json_schema_when_dict():
    a = BaseAgent(
        system_prompt="test",
        json_schema={"type": "object"},
        max_prompt_chars=10000,
    )
    args = a._build_cli_args(actual_prompt="hi")
    assert "--json-schema" in args
