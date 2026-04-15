"""Tests for daemon notification after manual analysis."""

from unittest.mock import patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, upsert_event
from scanner.core.monitor_store import get_event_monitor, upsert_event_monitor


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


class TestNotifyAfterAnalysis:
    def test_update_next_check_at_triggers_notify(self, db):
        """When next_check_at is updated, notify_daemon should be called."""
        upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        from scanner.core.monitor_store import update_next_check_at

        with patch("scanner.daemon.notify.notify_daemon") as mock_notify:
            update_next_check_at("ev1", "2026-04-21T09:00:00+08:00", "test reason", db)
            mock_notify.assert_called_once()

        mon = get_event_monitor("ev1", db)
        assert mon["next_check_at"] == "2026-04-21T09:00:00+08:00"

    def test_no_notify_when_clearing_next_check(self, db):
        """When next_check_at is set to None, no notification should fire."""
        upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        from scanner.core.monitor_store import update_next_check_at

        with patch("scanner.daemon.notify.notify_daemon") as mock_notify:
            update_next_check_at("ev1", None, None, db)
            mock_notify.assert_not_called()

    def test_no_notify_when_notify_false(self, db):
        """Daemon-internal calls pass notify=False to avoid self-signaling."""
        upsert_event(EventRow(event_id="ev1", title="Test", updated_at="now"), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

        from scanner.core.monitor_store import update_next_check_at

        with patch("scanner.daemon.notify.notify_daemon") as mock_notify:
            update_next_check_at("ev1", "2026-04-21T09:00:00+08:00", "test", db, notify=False)
            mock_notify.assert_not_called()
