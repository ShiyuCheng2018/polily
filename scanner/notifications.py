"""Notification system: macOS desktop + SQLite persistence."""

import subprocess
from datetime import UTC, datetime


def add_notification(
    db,
    *,
    title: str,
    body: str,
    event_id: str | None = None,
    market_id: str | None = None,
    trigger_source: str | None = None,
    action_result: str | None = None,
) -> None:
    """Persist a notification to SQLite."""
    db.conn.execute(
        """INSERT INTO notifications
        (created_at, event_id, market_id, title, body, trigger_source, action_result)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (datetime.now(UTC).isoformat(), event_id, market_id, title, body,
         trigger_source, action_result),
    )
    db.conn.commit()


def get_unread_notifications(db) -> list[dict]:
    """Get all unread notifications, newest first."""
    rows = db.conn.execute(
        "SELECT * FROM notifications WHERE is_read = 0 ORDER BY created_at DESC",
    ).fetchall()
    return [dict(r) for r in rows]


def mark_read(db, notification_id: int) -> None:
    """Mark a single notification as read."""
    db.conn.execute(
        "UPDATE notifications SET is_read = 1, read_at = ? WHERE id = ?",
        (datetime.now(UTC).isoformat(), notification_id),
    )
    db.conn.commit()


def mark_all_read(db) -> None:
    """Mark all unread notifications as read."""
    db.conn.execute(
        "UPDATE notifications SET is_read = 1, read_at = ? WHERE is_read = 0",
        (datetime.now(UTC).isoformat(),),
    )
    db.conn.commit()


def _escape_applescript(s: str) -> str:
    """Escape string for AppleScript — handle backslash and double quote."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def send_desktop_notification(title: str, body: str) -> None:
    """Send a macOS desktop notification via osascript."""
    safe_title = _escape_applescript(title)
    safe_body = _escape_applescript(body)
    script = f'display notification "{safe_body}" with title "Polily" subtitle "{safe_title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True)
