from scanner.config import MovementConfig, ScannerConfig


def test_movement_config_defaults():
    config = ScannerConfig()
    m = config.movement
    assert isinstance(m, MovementConfig)
    assert m.enabled is True
    assert m.magnitude_threshold == 70
    assert m.quality_threshold == 60
    assert m.daily_analysis_limit == 10
    assert m.poll_intervals["crypto"] == 10
    assert m.poll_intervals["political"] == 60
    assert m.poll_intervals["economic_data"] == 20
    assert m.poll_intervals["default"] == 30
    assert m.rolling_window_hours == 6
