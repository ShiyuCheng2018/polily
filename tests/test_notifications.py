"""Tests for notification system — macOS desktop + SQLite persistence."""

import tempfile
from pathlib import Path

from scanner.db import PolilyDB
from scanner.notifications import (
    add_notification,
    get_unread_notifications,
    mark_all_read,
    mark_read,
    send_desktop_notification,
)


def _make_db():
    tmp = tempfile.mkdtemp()
    return PolilyDB(Path(tmp) / "polily.db")


def test_add_and_get_unread():
    db = _make_db()
    add_notification(db, title="[WATCH] BTC 68000",
                     body="YES 0.65 -> 0.48 (-26%)",
                     market_id="0xabc", trigger_source="scheduled",
                     action_result="watch")
    unread = get_unread_notifications(db)
    assert len(unread) == 1
    assert unread[0]["title"] == "[WATCH] BTC 68000"
    assert unread[0]["market_id"] == "0xabc"
    assert unread[0]["trigger_source"] == "scheduled"
    assert unread[0]["is_read"] == 0
    db.close()


def test_mark_read():
    db = _make_db()
    add_notification(db, title="Test", body="Body")
    unread = get_unread_notifications(db)
    assert len(unread) == 1
    mark_read(db, unread[0]["id"])
    assert len(get_unread_notifications(db)) == 0
    db.close()


def test_mark_all_read():
    db = _make_db()
    add_notification(db, title="T1", body="B1")
    add_notification(db, title="T2", body="B2")
    add_notification(db, title="T3", body="B3")
    assert len(get_unread_notifications(db)) == 3
    mark_all_read(db)
    assert len(get_unread_notifications(db)) == 0
    db.close()


def test_unread_ordered_newest_first():
    db = _make_db()
    add_notification(db, title="First", body="B1")
    add_notification(db, title="Second", body="B2")
    unread = get_unread_notifications(db)
    assert unread[0]["title"] == "Second"
    assert unread[1]["title"] == "First"
    db.close()


def test_desktop_notification_calls_osascript(mocker):
    mock_run = mocker.patch("scanner.notifications.subprocess.run")
    send_desktop_notification("Test Title", "Test Body")
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "osascript"


def test_desktop_notification_escapes_quotes(mocker):
    mock_run = mocker.patch("scanner.notifications.subprocess.run")
    send_desktop_notification('He said "hello"', 'Body with "quotes"')
    mock_run.assert_called_once()
    script = mock_run.call_args[0][0][2]  # osascript -e <script>
    # Quotes should be escaped, not raw
    assert '\\"hello\\"' in script
