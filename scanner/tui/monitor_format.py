"""Formatting helpers for the Watchlist (monitor list) view."""

from __future__ import annotations

from datetime import UTC, datetime

_DASH = "—"

_LABEL_CN = {
    "consensus": "共识异动",
    "whale_move": "大单异动",
    "slow_build": "缓慢累积",
    "noise": "平静",
}

_HIGH_MAGNITUDE_THRESHOLD = 70.0


def pick_movement_color(label: str, magnitude: float) -> str:
    """Magnitude-driven color used across all movement surfaces.

    - `noise` is always green regardless of magnitude (it's the "quiet" bucket)
    - Any other label: red if magnitude ≥ 70, yellow otherwise

    Kept in one place so event_header / movement_sparkline / monitor list
    can't drift into different palettes for the same concept.
    """
    if label == "noise":
        return "green"
    return "red" if magnitude >= _HIGH_MAGNITUDE_THRESHOLD else "yellow"


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


def format_settlement_range(earliest: str | None, latest: str | None) -> str:
    """Render the event's settlement window, e.g. '2天6小时 ~ 40天16小时'.

    Single value (no tilde) when both sides render to the same string or when
    only one side is provided. Returns `—` when both sides are missing.

    Uses `scanner.tui.utils._relative` so the phrasing matches the detail
    page's countdown style.
    """
    if not earliest and not latest:
        return _DASH
    # One-sided becomes single value.
    if not earliest:
        earliest = latest
    if not latest:
        latest = earliest

    from scanner.tui.utils import _relative

    rel_early = _relative(earliest)
    rel_late = _relative(latest)

    if rel_early == rel_late:
        return rel_early
    return f"{rel_early} ~ {rel_late}"


def format_ai_version(count: int | None) -> str:
    """Show 'v5' for positive count, '—' for 0/None."""
    if not count:
        return _DASH
    return f"v{count}"


def format_movement(label: str | None, magnitude: float, quality: float) -> str:
    """Format movement status cell, e.g. '[green]平静[/green] M:31 Q:31'.

    Returns '—' when label is None or unknown. Color is magnitude-driven via
    `pick_movement_color` so the cell renders the same way as the detail-page
    movement views.
    """
    if not label or label not in _LABEL_CN:
        return _DASH
    label_cn = _LABEL_CN[label]
    color = pick_movement_color(label, magnitude)
    return f"[{color}]{label_cn}[/{color}] M:{magnitude:.0f} Q:{quality:.0f}"
