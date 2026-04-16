"""Tests for movement store — event-level."""
import pytest

from scanner.core.db import PolilyDB
from scanner.monitor.store import (
    append_movement,
    get_event_latest,
    get_event_movements,
    get_movement_summary,
    get_today_analysis_count,
    prune_old_movements,
)


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


class TestAppendMovement:
    def test_append_sub_market_movement(self, db):
        append_movement(
            event_id="ev1", market_id="m1",
            yes_price=0.55, prev_yes_price=0.53,
            trade_volume=100.0, bid_depth=500.0, ask_depth=300.0, spread=0.02,
            magnitude=45.0, quality=30.0, label="noise",
            db=db,
        )
        entries = get_event_movements("ev1", db, hours=1)
        assert len(entries) == 1
        assert entries[0]["market_id"] == "m1"
        assert entries[0]["yes_price"] == 0.55

    def test_append_event_level_movement(self, db):
        """market_id=None means event-level aggregate record."""
        append_movement(
            event_id="ev1", market_id=None,
            magnitude=0.0, quality=0.0, label="noise",
            snapshot='{"entropy": 0.82, "overround": 0.03}',
            db=db,
        )
        entries = get_event_movements("ev1", db, hours=1)
        assert len(entries) == 1
        assert entries[0]["market_id"] is None
        assert "entropy" in entries[0]["snapshot"]

    def test_append_with_no_price(self, db):
        append_movement(
            event_id="ev1", market_id="m1",
            yes_price=0.55, no_price=0.45,
            magnitude=50.0, quality=40.0, label="consensus",
            db=db,
        )
        entries = get_event_movements("ev1", db, hours=1)
        assert entries[0]["no_price"] == 0.45


class TestGetEventMovements:
    def test_returns_all_sub_market_and_event_level(self, db):
        append_movement(event_id="ev1", market_id="m1", magnitude=10, quality=5, label="noise", db=db)
        append_movement(event_id="ev1", market_id="m2", magnitude=20, quality=15, label="noise", db=db)
        append_movement(event_id="ev1", market_id=None, magnitude=0, quality=0, label="noise", db=db)
        entries = get_event_movements("ev1", db, hours=1)
        assert len(entries) == 3

    def test_does_not_return_other_events(self, db):
        append_movement(event_id="ev1", market_id="m1", magnitude=10, quality=5, label="noise", db=db)
        append_movement(event_id="ev2", market_id="m2", magnitude=20, quality=15, label="noise", db=db)
        entries = get_event_movements("ev1", db, hours=1)
        assert len(entries) == 1

    def test_ordered_by_created_at_desc(self, db):
        from datetime import UTC, datetime, timedelta
        now = datetime.now(UTC)
        # Manually insert with controlled timestamps
        for i in range(3):
            ts = (now - timedelta(minutes=i)).isoformat()
            db.conn.execute(
                "INSERT INTO movement_log (event_id, market_id, created_at, magnitude, quality, label) VALUES (?,?,?,?,?,?)",
                ("ev1", "m1", ts, float(i * 10), 0.0, "noise"),
            )
        db.conn.commit()
        entries = get_event_movements("ev1", db, hours=1)
        assert entries[0]["magnitude"] == 0.0  # most recent first


class TestGetEventLatest:
    def test_returns_latest_entry(self, db):
        append_movement(event_id="ev1", market_id="m1", yes_price=0.50, magnitude=10, quality=5, label="noise", db=db)
        append_movement(event_id="ev1", market_id="m1", yes_price=0.55, magnitude=20, quality=10, label="noise", db=db)
        latest = get_event_latest("ev1", db)
        assert latest is not None
        assert latest["yes_price"] == 0.55

    def test_returns_none_when_empty(self, db):
        assert get_event_latest("nonexistent", db) is None


class TestGetTodayAnalysisCount:
    def test_counts_triggered_analyses(self, db):
        append_movement(event_id="ev1", market_id="m1", magnitude=80, quality=60,
                       label="consensus", triggered_analysis=True, db=db)
        append_movement(event_id="ev1", market_id="m2", magnitude=70, quality=50,
                       label="whale_move", triggered_analysis=True, db=db)
        append_movement(event_id="ev1", market_id="m1", magnitude=30, quality=20,
                       label="noise", triggered_analysis=False, db=db)
        count = get_today_analysis_count("ev1", db)
        assert count == 2

    def test_scoped_to_event(self, db):
        append_movement(event_id="ev1", market_id="m1", magnitude=80, quality=60,
                       label="consensus", triggered_analysis=True, db=db)
        append_movement(event_id="ev2", market_id="m2", magnitude=80, quality=60,
                       label="consensus", triggered_analysis=True, db=db)
        assert get_today_analysis_count("ev1", db) == 1


class TestGetMovementSummary:
    def test_returns_summary_string(self, db):
        append_movement(event_id="ev1", market_id="m1", yes_price=0.55,
                       magnitude=45, quality=30, label="noise", db=db)
        summary = get_movement_summary("ev1", db)
        assert summary is not None
        assert "0.55" in summary

    def test_returns_none_when_empty(self, db):
        assert get_movement_summary("nonexistent", db) is None


class TestPrune:
    def test_prune_old_movements(self, db):
        from datetime import UTC, datetime, timedelta
        old_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        db.conn.execute(
            "INSERT INTO movement_log (event_id, created_at, magnitude, quality, label) VALUES (?,?,?,?,?)",
            ("ev1", old_ts, 0, 0, "noise"),
        )
        db.conn.commit()
        append_movement(event_id="ev1", market_id="m1", magnitude=10, quality=5, label="noise", db=db)
        pruned = prune_old_movements(db, days=7)
        assert pruned == 1
        remaining = get_event_movements("ev1", db, hours=24 * 30)
        assert len(remaining) == 1
