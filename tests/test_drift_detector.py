"""Tests for drift detection — rolling windows + CUSUM."""

from scanner.drift_detector import check_rolling_windows


class TestRollingWindows:
    def test_5min_spike_triggers(self):
        prices = [(300, 0.50), (0, 0.535)]
        alerts = check_rolling_windows(0.535, prices, {5: 0.03})
        assert len(alerts) == 1
        assert alerts[0]["window"] == 5
        assert alerts[0]["direction"] == "UP"

    def test_4h_drift_triggers(self):
        prices = [(14400, 0.50), (0, 0.63)]
        alerts = check_rolling_windows(0.63, prices, {240: 0.12})
        assert len(alerts) == 1

    def test_small_move_no_trigger(self):
        prices = [(1800, 0.50), (0, 0.51)]
        alerts = check_rolling_windows(0.51, prices, {30: 0.05})
        assert len(alerts) == 0

    def test_post_sleep_gap_triggers(self):
        prices = [(7200, 0.50), (0, 0.62)]
        alerts = check_rolling_windows(0.62, prices, {240: 0.12})
        assert len(alerts) == 1

    def test_empty_history(self):
        alerts = check_rolling_windows(0.50, [], {5: 0.03})
        assert alerts == []

    def test_single_entry_no_change(self):
        alerts = check_rolling_windows(0.50, [(10, 0.50)], {5: 0.03})
        assert alerts == []

    def test_multiple_windows_trigger(self):
        prices = [(300, 0.40), (0, 0.55)]
        alerts = check_rolling_windows(0.55, prices, {5: 0.03, 30: 0.05, 60: 0.08})
        assert len(alerts) == 3

    def test_downward_direction(self):
        prices = [(300, 0.60), (0, 0.55)]
        alerts = check_rolling_windows(0.55, prices, {5: 0.03})
        assert alerts[0]["direction"] == "DOWN"

    def test_exact_threshold_triggers(self):
        """Exactly at threshold should trigger (>=)."""
        prices = [(300, 0.50), (0, 0.53)]  # exactly 0.03
        alerts = check_rolling_windows(0.53, prices, {5: 0.03})
        assert len(alerts) == 1

    def test_picks_oldest_entry_in_window(self):
        """Should compare against oldest entry, not newest."""
        prices = [(250, 0.52), (150, 0.54), (50, 0.55)]  # oldest=0.52 in 5min window
        alerts = check_rolling_windows(0.56, prices, {5: 0.03})
        # change = 0.56 - 0.52 = 0.04 > 0.03 → trigger
        assert len(alerts) == 1
