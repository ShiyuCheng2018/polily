"""Tests for PolilyConfig defaults and field shape.

v0.10.0 (T7.4 / T2.6) deleted yaml-based `load_config()` and the
`deep_merge` helper. Yaml is no longer a config input — `db.config` is
canonical, with `load_config_from_db()` as the only loader. The tests
that previously asserted yaml-merge / yaml-default behavior now assert
the equivalent invariant on `PolilyConfig()` defaults directly.
"""

from polily.core.config import PolilyConfig


class TestPolilyConfigDefaults:
    def test_default_tier_a_min_score(self):
        config = PolilyConfig()
        assert config.scoring.thresholds.tier_a_min_score == 70

    def test_default_narrative_writer(self):
        """v0.12.0: default model bumped sonnet → opus.

        See AgentConfig docstring + v0.12.0 CHANGELOG for the upgrade
        rationale (long-context Manual + Strategy + Protocol stack
        benefits materially from Opus-tier reasoning).
        """
        config = PolilyConfig()
        assert config.ai.narrative_writer.model == "opus"
        assert config.ai.narrative_writer.timeout_seconds == 300


def test_movement_config_min_history_default():
    """Phase 0 Task 12: hardcoded _MIN_HISTORY/_STALE_SECONDS lifted into MovementConfig."""
    from polily.core.config import MovementConfig
    cfg = MovementConfig()
    assert cfg.min_history_entries == 5
    assert cfg.stale_threshold_seconds == 600


def test_agent_config_max_prompt_chars_default():
    """Phase 0 Task 13: DEFAULT_MAX_PROMPT_CHARS lifted into AgentConfig.

    v0.12.0: bumped 5000 → 100000. The pre-v0.12.0 default of 5000 chars
    was smaller than v0.12.0's combined manual + strategy + protocol
    prompt (~40 KB), forcing every dispatch through BaseAgent's broken
    temp-file fallback. 100000 is well under macOS ARG_MAX (1 MB) and
    leaves plenty of room for retry buffer + future strategy growth.
    """
    from polily.core.config import AgentConfig
    cfg = AgentConfig()
    assert cfg.max_prompt_chars == 100000


def test_agent_config_no_dead_fields():
    """Phase 0 Task 13: AgentConfig has only the 3 fields actually consumed.

    Removed: enabled, max_concurrent, max_candidates (zero consumers per audit).
    Kept: model, timeout_seconds, max_prompt_chars.
    """
    from polily.core.config import AgentConfig
    fields = set(AgentConfig.model_fields.keys())
    assert fields == {"model", "timeout_seconds", "max_prompt_chars"}, (
        f"AgentConfig should have only 3 fields after Phase 0; got: {fields}"
    )


def test_tui_config_heartbeat_default():
    """Phase 0 Task 14: HEARTBEAT_SECONDS lifted into new TuiConfig section."""
    from polily.core.config import PolilyConfig
    cfg = PolilyConfig()
    assert cfg.tui.heartbeat_seconds == 5.0
