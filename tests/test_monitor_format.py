"""Formatting helpers for the Watchlist (monitor list) view."""

from datetime import UTC, datetime, timedelta


def _in(delta: timedelta) -> str:
    # Pad +2s so test is robust against sub-minute truncation during computation.
    return (datetime.now(UTC) + delta + timedelta(seconds=2)).isoformat()


class TestFormatRelativeEn:
    def test_days_hours_minutes(self):
        from scanner.tui.monitor_format import format_relative_en

        assert format_relative_en(_in(timedelta(days=1, hours=11, minutes=30))) == "1d 11h 30m"

    def test_hours_minutes_only_when_under_day(self):
        from scanner.tui.monitor_format import format_relative_en

        assert format_relative_en(_in(timedelta(hours=11, minutes=30))) == "11h 30m"

    def test_minutes_only_when_under_hour(self):
        from scanner.tui.monitor_format import format_relative_en

        assert format_relative_en(_in(timedelta(minutes=45))) == "45m"

    def test_expired_returns_dash(self):
        from scanner.tui.monitor_format import format_relative_en

        assert format_relative_en(_in(timedelta(hours=-2))) == "—"

    def test_none_returns_dash(self):
        from scanner.tui.monitor_format import format_relative_en

        assert format_relative_en(None) == "—"

    def test_invalid_returns_dash(self):
        from scanner.tui.monitor_format import format_relative_en

        assert format_relative_en("not-a-date") == "—"


class TestFormatNextCheck:
    def test_combines_full_iso_and_relative(self):
        from scanner.tui.monitor_format import format_next_check

        iso = _in(timedelta(days=1, hours=11, minutes=30))
        result = format_next_check(iso)
        # Full date with year
        assert result.startswith(datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M"))
        # Relative in parens
        assert "(1d 11h 30m)" in result

    def test_none_returns_dash(self):
        from scanner.tui.monitor_format import format_next_check

        assert format_next_check(None) == "—"


class TestFormatAiVersion:
    def test_positive_count(self):
        from scanner.tui.monitor_format import format_ai_version

        assert format_ai_version(5) == "v5"
        assert format_ai_version(1) == "v1"

    def test_zero_shows_dash(self):
        from scanner.tui.monitor_format import format_ai_version

        assert format_ai_version(0) == "—"

    def test_none_shows_dash(self):
        from scanner.tui.monitor_format import format_ai_version

        assert format_ai_version(None) == "—"


class TestFormatSettlementRange:
    def test_same_earliest_and_latest_is_single_value(self):
        from scanner.tui.monitor_format import format_settlement_range

        iso = _in(timedelta(days=2, hours=6))
        out = format_settlement_range(iso, iso)
        assert "~" not in out
        assert "2天" in out

    def test_different_dates_joined_with_spaced_tilde(self):
        from scanner.tui.monitor_format import format_settlement_range

        early = _in(timedelta(days=2, hours=6))
        late = _in(timedelta(days=40, hours=16))
        out = format_settlement_range(early, late)
        assert " ~ " in out
        assert "2天" in out
        assert "40天" in out

    def test_both_none_returns_dash(self):
        from scanner.tui.monitor_format import format_settlement_range

        assert format_settlement_range(None, None) == "—"

    def test_only_one_provided_treats_as_single(self):
        from scanner.tui.monitor_format import format_settlement_range

        iso = _in(timedelta(days=5))
        out = format_settlement_range(iso, None)
        assert "~" not in out
        assert "5天" in out

        out2 = format_settlement_range(None, iso)
        assert "~" not in out2
        assert "5天" in out2


class TestPickMovementColor:
    """Magnitude-driven color policy, shared with event_header / movement_sparkline."""

    def test_noise_is_always_green(self):
        from scanner.tui.monitor_format import pick_movement_color

        assert pick_movement_color("noise", 0) == "green"
        assert pick_movement_color("noise", 85) == "green"  # even if someone writes a high-M noise row

    def test_non_noise_high_magnitude_is_red(self):
        from scanner.tui.monitor_format import pick_movement_color

        assert pick_movement_color("consensus", 72) == "red"
        assert pick_movement_color("slow_build", 85) == "red"  # high M beats label default
        assert pick_movement_color("whale_move", 90) == "red"

    def test_non_noise_low_magnitude_is_yellow(self):
        from scanner.tui.monitor_format import pick_movement_color

        assert pick_movement_color("consensus", 40) == "yellow"  # low M beats label default
        assert pick_movement_color("slow_build", 40) == "yellow"
        assert pick_movement_color("whale_move", 60) == "yellow"

    def test_threshold_is_70(self):
        from scanner.tui.monitor_format import pick_movement_color

        assert pick_movement_color("consensus", 69.9) == "yellow"
        assert pick_movement_color("consensus", 70.0) == "red"


class TestFormatMovement:
    def test_calm_uses_green(self):
        from scanner.tui.monitor_format import format_movement

        out = format_movement("noise", magnitude=31.0, quality=31.0)
        assert "平静" in out
        assert "M:31" in out
        assert "Q:31" in out
        assert "green" in out

    def test_consensus_high_magnitude_uses_red(self):
        from scanner.tui.monitor_format import format_movement

        out = format_movement("consensus", magnitude=72.0, quality=85.0)
        assert "共识异动" in out
        assert "red" in out

    def test_slow_build_high_magnitude_uses_red(self):
        """High-magnitude slow_build should render red even though label suggests calmer."""
        from scanner.tui.monitor_format import format_movement

        out = format_movement("slow_build", magnitude=85.0, quality=70.0)
        assert "缓慢累积" in out
        assert "red" in out

    def test_consensus_low_magnitude_uses_yellow(self):
        """Low-magnitude consensus should render yellow — magnitude drives color, not label."""
        from scanner.tui.monitor_format import format_movement

        out = format_movement("consensus", magnitude=40.0, quality=50.0)
        assert "共识异动" in out
        assert "yellow" in out

    def test_no_label_returns_dash(self):
        from scanner.tui.monitor_format import format_movement

        assert format_movement(None, magnitude=0, quality=0) == "—"

    def test_unknown_label_returns_dash(self):
        from scanner.tui.monitor_format import format_movement

        assert format_movement("mystery", magnitude=0, quality=0) == "—"
