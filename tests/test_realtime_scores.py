"""Tests for realtime scoring from movement_log data."""

import pytest
from scanner.db import PolilyDB
from scanner.movement import MovementResult
from scanner.movement_store import append_movement, get_price_status


@pytest.fixture
def db(tmp_path):
    _db = PolilyDB(tmp_path / "test.db")
    yield _db
    _db.close()


def test_append_movement_with_orderbook(db):
    """movement_log should store bid_depth, ask_depth, spread."""
    result = MovementResult(magnitude=50.0, quality=30.0)
    append_movement("m1", result,
                    yes_price=0.60, prev_yes_price=0.55,
                    trade_volume=5000.0,
                    bid_depth=140000.0, ask_depth=18000.0, spread=0.013,
                    db=db)

    row = db.conn.execute("SELECT * FROM movement_log WHERE market_id = 'm1'").fetchone()
    assert row["bid_depth"] == 140000.0
    assert row["ask_depth"] == 18000.0
    assert row["spread"] == 0.013


def test_get_price_status_includes_orderbook(db):
    """get_price_status should return orderbook data."""
    append_movement("m1", MovementResult(magnitude=40.0, quality=25.0),
                    yes_price=0.60, prev_yes_price=0.55,
                    bid_depth=100000.0, ask_depth=50000.0, spread=0.015,
                    db=db)

    status = get_price_status("m1", db, watch_price=0.55)
    assert status["bid_depth"] == 100000.0
    assert status["ask_depth"] == 50000.0
    assert status["spread"] == 0.015


def test_get_price_status_orderbook_defaults(db):
    """Orderbook fields should default to 0/None when not provided."""
    append_movement("m1", MovementResult(magnitude=10.0, quality=5.0),
                    yes_price=0.50, prev_yes_price=0.48, db=db)

    status = get_price_status("m1", db, watch_price=0.48)
    assert status["bid_depth"] == 0.0
    assert status["ask_depth"] == 0.0
    assert status["spread"] is None


def test_realtime_score_recalculation(db):
    """Structure score should change when computed with different price/depth."""
    from scanner.scoring import compute_structure_score
    from scanner.config import ScannerConfig
    from scanner.models import Market, BookLevel
    from datetime import datetime, UTC, timedelta

    config = ScannerConfig()
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
    score1 = compute_structure_score(m1, config.scoring.weights)

    # Same market with thin depth
    m2 = Market(
        market_id="m1", title="Test", outcomes=["Yes", "No"],
        yes_price=0.50, spread_pct_yes=0.01,
        data_fetched_at=datetime.now(UTC),
        resolution_time=datetime.fromisoformat(resolution),
        book_depth_bids=[BookLevel(price=1.0, size=500)],
        book_depth_asks=[BookLevel(price=1.0, size=300)],
    )
    score2 = compute_structure_score(m2, config.scoring.weights)

    # Good depth should score higher on liquidity
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
    score3 = compute_structure_score(m3, config.scoring.weights)

    # 0.50 (sweet zone) should score higher on probability space than 0.95 (extreme)
    assert score1.probability_space > score3.probability_space
