"""Tests for config loading and merging."""

import tempfile
from pathlib import Path

from polily.core.config import deep_merge, load_config


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3}
        assert deep_merge(base, override) == {"a": 1, "b": 3}

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99}}
        result = deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 99}, "b": 3}

    def test_add_new_key(self):
        base = {"a": 1}
        override = {"b": 2}
        assert deep_merge(base, override) == {"a": 1, "b": 2}

    def test_override_dict_with_scalar(self):
        base = {"a": {"x": 1}}
        override = {"a": "replaced"}
        assert deep_merge(base, override) == {"a": "replaced"}

    def test_empty_override(self):
        base = {"a": 1}
        assert deep_merge(base, {}) == {"a": 1}

    def test_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        override = {"a": {"x": 2}}
        deep_merge(base, override)
        assert base["a"]["x"] == 1  # base unchanged


class TestLoadConfig:
    def test_load_example_config(self):
        config = load_config(Path("config.example.yaml"))
        assert config is not None
        assert config.scoring.thresholds.tier_a_min_score == 70

    def test_load_minimal_config_merges_with_defaults(self):
        config = load_config(Path("config.minimal.yaml"), defaults_path=Path("config.example.yaml"))
        # inherits all defaults from example
        assert config.scoring.thresholds.tier_a_min_score == 70

    def test_ai_config_has_narrative_writer(self):
        config = load_config(Path("config.example.yaml"))
        assert config.ai.narrative_writer.model == "sonnet"
        assert config.ai.narrative_writer.timeout_seconds == 300

    def test_custom_yaml(self):
        yaml_content = """
scoring:
  thresholds:
    tier_a_min_score: 80
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_config(Path(f.name), defaults_path=Path("config.example.yaml"))
            assert config.scoring.thresholds.tier_a_min_score == 80
