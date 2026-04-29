"""Tests for the yaml snapshot generator (design §4.4)."""
from __future__ import annotations

import yaml as yaml_lib

from polily.core.config import PolilyConfig
from polily.core.config_yaml import generate_yaml


def test_generate_yaml_writes_file_with_read_only_header(tmp_path):
    target = tmp_path / "config.yaml"
    generate_yaml(PolilyConfig(), target)

    content = target.read_text(encoding="utf-8")
    assert "READ ONLY" in content
    assert "polily 从数据库自动生成" in content
    assert "生成时间:" in content
    assert "polily 版本:" in content


def test_generate_yaml_body_is_valid_yaml_matching_pydantic_dump(tmp_path):
    target = tmp_path / "config.yaml"
    config = PolilyConfig()
    generate_yaml(config, target)

    content = target.read_text(encoding="utf-8")
    # Strip header (everything until the first non-comment line)
    body = "\n".join(
        line for line in content.splitlines()
        if not line.startswith("#") and line.strip()
    )
    parsed = yaml_lib.safe_load(body)
    assert parsed["movement"]["magnitude_threshold"] == 70
    assert parsed["wallet"]["starting_balance"] == 100.0
    assert parsed["api"]["user_agent"].startswith("polily/")  # default_factory


def test_generate_yaml_overwrites_existing_file(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("# stale content\nmovement:\n  magnitude_threshold: 999\n")

    generate_yaml(PolilyConfig(), target)

    content = target.read_text(encoding="utf-8")
    assert "999" not in content
    assert "magnitude_threshold: 70" in content


def test_generate_yaml_includes_user_agent_even_though_ephemeral(tmp_path):
    """yaml is the only place where users see the resolved user_agent.
    Per design §4.4 — model_dump() includes it (Pydantic just computed it)."""
    target = tmp_path / "config.yaml"
    generate_yaml(PolilyConfig(), target)

    content = target.read_text(encoding="utf-8")
    assert "user_agent: polily/" in content
