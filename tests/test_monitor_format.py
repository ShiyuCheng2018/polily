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


class TestFormatMovement:
    def test_calm_label_green(self):
        from scanner.tui.monitor_format import format_movement

        out = format_movement("noise", magnitude=31.0, quality=31.0)
        assert "平静" in out
        assert "M:31" in out
        assert "Q:31" in out
        assert "green" in out  # Rich markup color

    def test_consensus_label_red(self):
        from scanner.tui.monitor_format import format_movement

        out = format_movement("consensus", magnitude=72.0, quality=85.0)
        assert "共识异动" in out
        assert "M:72" in out
        assert "Q:85" in out
        assert "red" in out

    def test_whale_move_label_red(self):
        from scanner.tui.monitor_format import format_movement

        out = format_movement("whale_move", magnitude=60.0, quality=70.0)
        assert "大单异动" in out
        assert "red" in out

    def test_slow_build_label_yellow(self):
        from scanner.tui.monitor_format import format_movement

        out = format_movement("slow_build", magnitude=40.0, quality=50.0)
        assert "缓慢累积" in out
        assert "yellow" in out

    def test_no_label_returns_dash(self):
        from scanner.tui.monitor_format import format_movement

        assert format_movement(None, magnitude=0, quality=0) == "—"

    def test_unknown_label_returns_dash(self):
        from scanner.tui.monitor_format import format_movement

        assert format_movement("mystery", magnitude=0, quality=0) == "—"
