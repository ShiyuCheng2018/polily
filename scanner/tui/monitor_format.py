"""Formatting helpers for the Watchlist (monitor list) view."""

from __future__ import annotations

from datetime import UTC, datetime

_DASH = "—"

_MOVEMENT_LABELS = {
    "consensus": ("共识异动", "red"),
    "whale_move": ("大单异动", "red"),
    "slow_build": ("缓慢累积", "yellow"),
    "noise": ("平静", "green"),
}


def format_relative_en(iso_time: str | None) -> str:
    """Compact English relative time, e.g. '1d 11h 30m' or '11h 30m' or '45m'.

    Returns `—` for None, invalid input, or past times.
    """
    if not iso_time:
        return _DASH
    try:
        target = datetime.fromisoformat(iso_time)
    except (ValueError, TypeError):
        return _DASH
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    total_seconds = int((target - datetime.now(UTC)).total_seconds())
    if total_seconds <= 0:
        return _DASH

    days = total_seconds // 86400
    hours = (total_seconds % 86400) // 3600
    minutes = (total_seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def format_next_check(iso_time: str | None) -> str:
    """Full ISO date + relative in parens, e.g. '2026-04-21 09:00 (1d 11h 30m)'."""
    if not iso_time:
        return _DASH
    try:
        target = datetime.fromisoformat(iso_time)
    except (ValueError, TypeError):
        return _DASH
    if target.tzinfo is None:
        target = target.replace(tzinfo=UTC)
    date_str = target.strftime("%Y-%m-%d %H:%M")
    rel = format_relative_en(iso_time)
    if rel == _DASH:
        return date_str
    return f"{date_str} ({rel})"


def format_ai_version(count: int | None) -> str:
    """Show 'v5' for positive count, '—' for 0/None."""
    if not count:
        return _DASH
    return f"v{count}"


def format_movement(label: str | None, magnitude: float, quality: float) -> str:
    """Format movement status cell, e.g. '[green]平静[/green] M:31 Q:31'.

    Returns '—' when label is None or unknown. Colors follow 3-band palette:
    红 for consensus/whale_move, 黄 for slow_build, 绿 for noise.
    """
    if not label:
        return _DASH
    entry = _MOVEMENT_LABELS.get(label)
    if not entry:
        return _DASH
    label_cn, color = entry
    return f"[{color}]{label_cn}[/{color}] M:{magnitude:.0f} Q:{quality:.0f}"
