"""Tests for event-level auto_monitor toggle."""
import json

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.monitor_store import get_active_monitors, get_event_monitor
from polily.daemon.auto_monitor import toggle_auto_monitor


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed(db, event_id="ev1"):
    upsert_event(EventRow(event_id=event_id, title="Test Event", updated_at="now"), db)
    upsert_market(MarketRow(
        market_id="m1", event_id=event_id, question="Q",
        yes_price=0.55, no_price=0.45, updated_at="now",
    ), db)


class TestToggleAutoMonitor:
    def test_enable_creates_monitor(self, db):
        _seed(db)
        toggle_auto_monitor("ev1", enable=True, db=db)
        monitor = get_event_monitor("ev1", db)
        assert monitor is not None
        assert monitor["auto_monitor"] == 1

    def test_enable_records_price_snapshot(self, db):
        _seed(db)
        toggle_auto_monitor("ev1", enable=True, db=db)
        monitor = get_event_monitor("ev1", db)
        assert monitor["price_snapshot"] is not None
        snapshot = json.loads(monitor["price_snapshot"])
        assert "m1" in snapshot
        assert snapshot["m1"]["yes"] == 0.55

    def test_disable_clears_auto_monitor(self, db):
        _seed(db)
        toggle_auto_monitor("ev1", enable=True, db=db)
        toggle_auto_monitor("ev1", enable=False, db=db)
        monitor = get_event_monitor("ev1", db)
        assert monitor["auto_monitor"] == 0

    def test_enable_appears_in_active_monitors(self, db):
        _seed(db, "ev1")
        _seed(db, "ev2")
        toggle_auto_monitor("ev1", enable=True, db=db)
        active = get_active_monitors(db)
        assert "ev1" in active
        assert "ev2" not in active

    def test_toggle_nonexistent_event_is_noop(self, db):
        """Should not raise for nonexistent event."""
        toggle_auto_monitor("nonexistent", enable=True, db=db)
        # Just no monitor created (event doesn't exist for FK)
        # or silently fails — either way no crash

    def test_double_enable_is_idempotent(self, db):
        _seed(db)
        toggle_auto_monitor("ev1", enable=True, db=db)
        toggle_auto_monitor("ev1", enable=True, db=db)
        active = get_active_monitors(db)
        assert active.count("ev1") == 1
