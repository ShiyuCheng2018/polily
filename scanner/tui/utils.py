"""Shared TUI formatting utilities."""

from datetime import UTC, datetime


def format_countdown(iso_time: str | None) -> str:
    """Format an ISO timestamp as 'MM-DD HH:MM (Xd Xh)' with countdown.

    Returns '?' if iso_time is None or invalid.
    """
    if not iso_time:
        return "?"
    try:
        target = datetime.fromisoformat(iso_time)
        if target.tzinfo is None:
            target = target.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        delta = target - now

        # Date part: MM-DD HH:MM
        date_str = target.strftime("%m-%d %H:%M")

        # Countdown part
        total_seconds = int(delta.total_seconds())
        if total_seconds <= 0:
            return f"{date_str} (已过期)"

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60

        if days > 0:
            countdown = f"{days}天{hours}小时"
        elif hours > 0:
            countdown = f"{hours}小时{minutes}分"
        else:
            countdown = f"{minutes}分钟"

        return f"{date_str} ({countdown})"
    except (ValueError, TypeError):
        return "?"
