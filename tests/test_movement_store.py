import pytest
from pathlib import Path

from scanner.db import PolilyDB
from scanner.movement import MovementResult, MovementSignals
from scanner.movement_store import (
    append_movement, get_recent_movements, get_movement_summary,
    prune_old_movements, get_latest_movement, get_price_status,
)


@pytest.fixture
def db(tmp_path):
    _db = PolilyDB(tmp_path / "test.db")
    yield _db
    _db.close()


def test_append_and_retrieve(db):
    result = MovementResult(magnitude=75.0, quality=65.0)
    append_movement("market_1", result, yes_price=0.55, prev_yes_price=0.50, db=db)

    recent = get_recent_movements("market_1", db, hours=1)
    assert len(recent) == 1
    assert recent[0]["magnitude"] == 75.0
    assert recent[0]["quality"] == 65.0
    assert recent[0]["label"] == "consensus"
    assert recent[0]["yes_price"] == 0.55


def test_get_recent_respects_time_window(db):
    append_movement("market_1", MovementResult(magnitude=50.0, quality=50.0),
                    yes_price=0.50, prev_yes_price=0.48, db=db)
    append_movement("market_1", MovementResult(magnitude=60.0, quality=60.0),
                    yes_price=0.52, prev_yes_price=0.50, db=db)

    recent = get_recent_movements("market_1", db, hours=1)
    assert len(recent) == 2


def test_movement_summary_for_ai(db):
    append_movement("m1", MovementResult(magnitude=50.0, quality=40.0),
                    yes_price=0.50, prev_yes_price=0.48, db=db)
    append_movement("m1", MovementResult(magnitude=80.0, quality=70.0),
                    yes_price=0.55, prev_yes_price=0.50, db=db)

    summary = get_movement_summary("m1", db, hours=6)
    assert isinstance(summary, str)
    assert "0.50" in summary or "0.55" in summary


def test_movement_summary_none_when_empty(db):
    summary = get_movement_summary("nonexistent", db, hours=6)
    assert summary is None


def test_triggered_analysis_in_summary(db):
    append_movement("m1", MovementResult(magnitude=82.0, quality=71.0),
                    yes_price=0.55, prev_yes_price=0.50, triggered_analysis=True, db=db)

    summary = get_movement_summary("m1", db, hours=6)
    assert "TRIGGERED AI" in summary


def test_prune_old_movements(db):
    """Entries older than cutoff should be deleted."""
    from datetime import UTC, datetime, timedelta

    # Insert an old entry directly with a timestamp 10 days ago
    old_ts = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    db.conn.execute(
        """INSERT INTO movement_log
        (market_id, created_at, magnitude, quality, label, snapshot)
        VALUES (?, ?, ?, ?, ?, ?)""",
        ("m1", old_ts, 50.0, 40.0, "noise", "{}"),
    )
    db.conn.commit()

    # Insert a recent entry via normal path
    append_movement("m1", MovementResult(magnitude=60.0, quality=60.0),
                    yes_price=0.55, prev_yes_price=0.50, db=db)

    deleted = prune_old_movements(db, days=7)
    assert deleted == 1  # only the old one

    remaining = get_recent_movements("m1", db, hours=24 * 30)
    assert len(remaining) == 1
    assert remaining[0]["magnitude"] == 60.0


def test_get_latest_movement(db):
    """Should return the most recent movement entry for a market."""
    append_movement("m1", MovementResult(magnitude=30.0, quality=20.0),
                    yes_price=0.50, prev_yes_price=0.48, db=db)
    append_movement("m1", MovementResult(magnitude=45.0, quality=35.0),
                    yes_price=0.55, prev_yes_price=0.50, db=db)

    latest = get_latest_movement("m1", db)
    assert latest is not None
    assert latest["yes_price"] == 0.55
    assert latest["magnitude"] == 45.0


def test_get_latest_movement_none_when_empty(db):
    latest = get_latest_movement("nonexistent", db)
    assert latest is None


def test_get_price_status(db):
    """Should return structured status with price, change, and movement info."""
    append_movement("m1", MovementResult(magnitude=40.0, quality=25.0),
                    yes_price=0.60, prev_yes_price=0.50, trade_volume=5000.0, db=db)

    status = get_price_status("m1", db, watch_price=0.50)
    assert status is not None
    assert status["current_price"] == 0.60
    assert status["watch_price"] == 0.50
    assert abs(status["change_pct"] - 20.0) < 0.1  # +20%
    assert status["magnitude"] == 40.0
    assert status["quality"] == 25.0
    assert status["label"] == "noise"
    assert status["significant_change"] is True  # >5% change


def test_get_price_status_no_data(db):
    status = get_price_status("nonexistent", db, watch_price=0.50)
    assert status is None


def test_get_price_status_small_change(db):
    """Small change should not be flagged as significant."""
    append_movement("m1", MovementResult(magnitude=10.0, quality=5.0),
                    yes_price=0.51, prev_yes_price=0.50, db=db)

    status = get_price_status("m1", db, watch_price=0.50)
    assert status["significant_change"] is False  # only 2% change
