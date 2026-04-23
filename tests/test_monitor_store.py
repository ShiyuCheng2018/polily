"""Tests for event monitor store operations."""
import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event
from polily.core.monitor_store import (
    get_active_monitors,
    get_event_monitor,
    upsert_event_monitor,
)


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _setup_event(db, event_id="ev1"):
    upsert_event(EventRow(event_id=event_id, title=f"Event {event_id}", updated_at="now"), db)


class TestMonitorStore:
    def test_upsert_and_get_event_monitor(self, db):
        _setup_event(db, "ev1")
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        monitor = get_event_monitor("ev1", db)
        assert monitor is not None
        assert monitor["auto_monitor"] == 1
        assert monitor["updated_at"] is not None

    def test_upsert_with_price_snapshot(self, db):
        _setup_event(db, "ev1")
        snapshot = '{"m1": {"yes": 0.55, "no": 0.45}}'
        upsert_event_monitor("ev1", auto_monitor=True, price_snapshot=snapshot, db=db)
        monitor = get_event_monitor("ev1", db)
        assert monitor["price_snapshot"] == snapshot

    def test_upsert_toggle_off(self, db):
        _setup_event(db, "ev1")
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        upsert_event_monitor("ev1", auto_monitor=False, db=db)
        monitor = get_event_monitor("ev1", db)
        assert monitor["auto_monitor"] == 0

    def test_get_active_monitors(self, db):
        _setup_event(db, "ev1")
        _setup_event(db, "ev2")
        _setup_event(db, "ev3")
        upsert_event_monitor("ev1", auto_monitor=True, db=db)
        upsert_event_monitor("ev2", auto_monitor=False, db=db)
        upsert_event_monitor("ev3", auto_monitor=True, db=db)
        active = get_active_monitors(db)
        assert sorted(active) == ["ev1", "ev3"]

    def test_get_nonexistent_monitor(self, db):
        assert get_event_monitor("nonexistent", db) is None
