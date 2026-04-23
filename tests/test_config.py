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
        assert config.filters.max_spread_pct == 0.04
        assert config.scoring.weights.objective_verifiability == 25

    def test_load_minimal_config_merges_with_defaults(self):
        config = load_config(Path("config.minimal.yaml"), defaults_path=Path("config.example.yaml"))
        # minimal sets discipline values
        assert config.discipline.account_size_usd == 150
        assert config.discipline.max_single_trade_usd == 20
        # inherits all other defaults from example
        assert config.filters.max_spread_pct == 0.04
        assert config.scoring.weights.objective_verifiability == 25

    def test_scoring_weights_sum_to_100(self):
        config = load_config(Path("config.example.yaml"))
        w = config.scoring.weights
        total = (
            w.liquidity_structure + w.objective_verifiability
            + w.probability_space + w.time_structure
            + w.trading_friction
        )
        assert total == 100

    def test_filters_thresholds_consistent(self):
        config = load_config(Path("config.example.yaml"))
        f = config.filters
        assert f.hard_reject_below_yes_price < f.min_yes_price
        assert f.hard_reject_above_yes_price > f.max_yes_price
        assert f.preferred_min_yes_price >= f.min_yes_price
        assert f.preferred_max_yes_price <= f.max_yes_price

    def test_ai_config_has_narrative_writer(self):
        config = load_config(Path("config.example.yaml"))
        assert config.ai.narrative_writer.model == "sonnet"
        assert config.ai.narrative_writer.timeout_seconds == 300

    def test_custom_yaml(self):
        yaml_content = """
filters:
  max_spread_pct: 0.02
scoring:
  weights:
    liquidity_structure: 35
    objective_verifiability: 20
    probability_space: 20
    time_structure: 15
    trading_friction: 10
"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(yaml_content)
            f.flush()
            config = load_config(Path(f.name), defaults_path=Path("config.example.yaml"))
            assert config.filters.max_spread_pct == 0.02
            assert config.scoring.weights.liquidity_structure == 35
