from scanner.core.config import MovementConfig, ScannerConfig


def test_movement_config_defaults():
    config = ScannerConfig()
    m = config.movement
    assert isinstance(m, MovementConfig)
    assert m.enabled is True
    assert m.magnitude_threshold == 70
    assert m.quality_threshold == 60
    assert m.daily_analysis_limit == 10
    assert m.rolling_window_hours == 6
