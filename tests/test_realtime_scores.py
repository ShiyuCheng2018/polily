"""Tests for realtime scoring from movement_log data."""

import pytest

from scanner.core.db import PolilyDB
from scanner.monitor.store import append_movement


@pytest.fixture
def db(tmp_path):
    _db = PolilyDB(tmp_path / "test.db")
    yield _db
    _db.close()


def test_append_movement_with_orderbook(db):
    """movement_log should store bid_depth, ask_depth, spread."""
    append_movement(
        event_id="ev1", market_id="m1",
        yes_price=0.60, prev_yes_price=0.55,
        trade_volume=5000.0, magnitude=50.0, quality=30.0, label="whale_move",
        bid_depth=140000.0, ask_depth=18000.0, spread=0.013,
        db=db,
    )
    db.conn.commit()

    row = db.conn.execute("SELECT * FROM movement_log WHERE market_id = 'm1'").fetchone()
    assert row["bid_depth"] == 140000.0
    assert row["ask_depth"] == 18000.0
    assert row["spread"] == 0.013


def test_realtime_score_recalculation(db):
    """Structure score should change when computed with different price/depth."""
    from datetime import UTC, datetime, timedelta

    from scanner.core.models import BookLevel, Market
    from scanner.scan.scoring import compute_structure_score

    resolution = (datetime.now(UTC) + timedelta(days=2)).isoformat()

    # Market with good depth
    m1 = Market(
        market_id="m1", title="Test", outcomes=["Yes", "No"],
        yes_price=0.50, spread_pct_yes=0.01,
        data_fetched_at=datetime.now(UTC),
        resolution_time=datetime.fromisoformat(resolution),
        book_depth_bids=[BookLevel(price=1.0, size=100000)],
        book_depth_asks=[BookLevel(price=1.0, size=80000)],
    )
    score1 = compute_structure_score(m1)

    # Same market with thin depth
    m2 = Market(
        market_id="m1", title="Test", outcomes=["Yes", "No"],
        yes_price=0.50, spread_pct_yes=0.01,
        data_fetched_at=datetime.now(UTC),
        resolution_time=datetime.fromisoformat(resolution),
        book_depth_bids=[BookLevel(price=1.0, size=500)],
        book_depth_asks=[BookLevel(price=1.0, size=300)],
    )
    score2 = compute_structure_score(m2)

    assert score1.liquidity_structure > score2.liquidity_structure

    # Same market with different price (probability space changes)
    m3 = Market(
        market_id="m1", title="Test", outcomes=["Yes", "No"],
        yes_price=0.95, spread_pct_yes=0.01,
        data_fetched_at=datetime.now(UTC),
        resolution_time=datetime.fromisoformat(resolution),
        book_depth_bids=[BookLevel(price=1.0, size=100000)],
        book_depth_asks=[BookLevel(price=1.0, size=80000)],
    )
    score3 = compute_structure_score(m3)

    assert score1.probability_space > score3.probability_space
