"""Tests for TUI formatting utilities."""

from datetime import UTC, datetime, timedelta

from scanner.tui.utils import format_countdown


def test_format_countdown_none():
    assert format_countdown(None) == "?"
    assert format_countdown("") == "?"


def test_format_countdown_days():
    future = (datetime.now(UTC) + timedelta(days=2, hours=3)).isoformat()
    result = format_countdown(future)
    assert "2天" in result
    assert "-" in result  # date part MM-DD


def test_format_countdown_hours():
    future = (datetime.now(UTC) + timedelta(hours=5, minutes=15)).isoformat()
    result = format_countdown(future)
    assert "5小时" in result
    assert "分" in result


def test_format_countdown_minutes():
    future = (datetime.now(UTC) + timedelta(minutes=20)).isoformat()
    result = format_countdown(future)
    assert "分钟" in result


def test_format_countdown_expired():
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    result = format_countdown(past)
    assert "已过期" in result


def test_format_countdown_invalid():
    assert format_countdown("not-a-date") == "?"


def test_format_countdown_has_date_and_countdown():
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    result = format_countdown(future)
    # Should have date part and countdown in parens
    assert "(" in result and ")" in result
