"""Tests for drift detection — rolling windows + CUSUM."""


from scanner.monitor.drift import CusumAccumulator, build_price_history, check_rolling_windows


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


class TestCusum:
    def test_accumulates_small_upward_moves(self):
        """Consecutive small moves trigger after ~30 ticks."""
        cusum = CusumAccumulator(drift=0.003, threshold=0.06)
        triggered = False
        # Each tick: 0.005 - 0.003 = 0.002 net. Need 0.06/0.002 = 30 ticks
        for _i in range(35):
            alerts = cusum.update(0.005)
            if alerts:
                triggered = True
                assert alerts[0]["direction"] == "UP"
                break
        assert triggered

    def test_oscillation_no_trigger(self):
        cusum = CusumAccumulator(drift=0.003, threshold=0.06)
        for _ in range(100):
            cusum.update(0.004)
            cusum.update(-0.004)
        assert cusum.s_pos < 0.06
        assert cusum.s_neg < 0.06

    def test_resets_after_trigger(self):
        cusum = CusumAccumulator(drift=0.003, threshold=0.06)
        triggered_at = None
        for i in range(35):
            alerts = cusum.update(0.005)
            if alerts and triggered_at is None:
                triggered_at = i
                # Immediately after trigger, accumulator resets to 0
                assert cusum.s_pos == 0
                break
        assert triggered_at is not None

    def test_downward_drift(self):
        cusum = CusumAccumulator(drift=0.003, threshold=0.06)
        triggered_down = False
        for _ in range(35):
            alerts = cusum.update(-0.005)
            if any(a["direction"] == "DOWN" for a in alerts):
                triggered_down = True
                break
        assert triggered_down

    def test_large_gap_triggers_immediately(self):
        """Single large jump triggers immediately."""
        cusum = CusumAccumulator(drift=0.003, threshold=0.06)
        alerts = cusum.update(0.10)
        assert len(alerts) == 1

    def test_warm_up_from_history(self):
        """warm_up should restore accumulator state."""
        cusum = CusumAccumulator(drift=0.003, threshold=0.06)
        # Feed 15 ticks of 0.005 via warm_up (not enough to trigger)
        cusum.warm_up([0.005] * 15)
        # s_pos should be 15 * 0.002 = 0.03
        assert 0.02 < cusum.s_pos < 0.04
        # A few more should trigger
        triggered = False
        for _ in range(20):
            alerts = cusum.update(0.005)
            if alerts:
                triggered = True
                break
        assert triggered


class TestBuildPriceHistory:
    def test_builds_from_movement_log(self, tmp_path):
        from scanner.core.db import PolilyDB
        from scanner.monitor.models import MovementResult
        from scanner.monitor.store import append_movement

        db = PolilyDB(tmp_path / "test.db")
        for price in [0.50, 0.51, 0.52]:
            append_movement("m1", MovementResult(magnitude=10, quality=10),
                           yes_price=price, prev_yes_price=price - 0.01, db=db)

        history = build_price_history("m1", db)
        assert len(history) == 3
        assert history[0][0] <= history[-1][0]
        db.close()

    def test_empty_market(self, tmp_path):
        from scanner.core.db import PolilyDB

        db = PolilyDB(tmp_path / "test.db")
        history = build_price_history("nonexistent", db)
        assert history == []
        db.close()

    def test_end_to_end_drift(self, tmp_path):
        """Gradual 12% drift over 4 hours triggers rolling window."""
        from datetime import UTC, datetime, timedelta

        from scanner.core.db import PolilyDB

        db = PolilyDB(tmp_path / "test.db")
        now = datetime.now(UTC)
        base = 0.50
        for i in range(24):
            price = base + i * 0.006  # +0.6% per entry = ~14% total
            ts = (now - timedelta(minutes=240 - i * 10)).isoformat()
            db.conn.execute(
                "INSERT INTO movement_log (market_id, created_at, yes_price, magnitude, quality, label, snapshot) VALUES (?, ?, ?, 10, 10, 'noise', '{}')",
                ("m1", ts, price))
        db.conn.commit()

        history = build_price_history("m1", db)
        current = base + 23 * 0.006  # 0.638
        alerts = check_rolling_windows(current, history, {240: 0.12})
        assert len(alerts) > 0
        db.close()
