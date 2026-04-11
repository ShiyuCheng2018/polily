"""Shared TUI formatting utilities."""

from datetime import UTC, datetime


def _relative(iso_time: str) -> str:
    """Return relative time string like '6天8小时' or '已过期'."""
    try:
        target = datetime.fromisoformat(iso_time)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        total_seconds = int((target - datetime.now(UTC)).total_seconds())
        if total_seconds <= 0:
            return "已过期"
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        if days > 0:
            return f"{days}天{hours}小时"
        if hours > 0:
            return f"{hours}小时{minutes}分"
        return f"{minutes}分钟"
    except (ValueError, TypeError):
        return "?"


def format_countdown(iso_time: str | None) -> str:
    """Format as 'MM-DD HH:MM (6天8小时)'. For sub-market rows."""
    if not iso_time:
        return "?"
    try:
        target = datetime.fromisoformat(iso_time)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        date_str = target.strftime("%m-%d %H:%M")
        rel = _relative(iso_time)
        return f"{date_str} ({rel})"
    except (ValueError, TypeError):
        return "?"


def format_countdown_range(earliest: str | None, latest: str | None) -> str:
    """Format event-level date range like '6天~264天' or single date."""
    if not earliest and not latest:
        return "?"
    if not earliest:
        earliest = latest
    if not latest:
        latest = earliest

    rel_early = _relative(earliest)
    rel_late = _relative(latest)

    if earliest == latest or rel_early == rel_late:
        return rel_early

    return f"{rel_early}~{rel_late}"
