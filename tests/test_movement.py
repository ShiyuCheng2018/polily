from datetime import UTC, datetime, timedelta

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.monitor.models import MovementResult, MovementSignals
from scanner.monitor.store import append_movement


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def test_movement_signals_defaults():
    s = MovementSignals()
    assert s.price_z_score == 0.0
    assert s.volume_ratio == 0.0
    assert s.book_imbalance == 0.0
    assert s.trade_concentration == 0.0
    assert s.open_interest_delta == 0.0


def test_movement_result_label():
    r = MovementResult(magnitude=80.0, quality=75.0)
    assert r.label == "consensus"

    r2 = MovementResult(magnitude=80.0, quality=30.0)
    assert r2.label == "whale_move"

    r3 = MovementResult(magnitude=30.0, quality=75.0)
    assert r3.label == "slow_build"

    r4 = MovementResult(magnitude=30.0, quality=30.0)
    assert r4.label == "noise"


def test_movement_result_should_trigger():
    r = MovementResult(magnitude=80.0, quality=75.0)
    assert r.should_trigger(m_threshold=70, q_threshold=60) is True

    r2 = MovementResult(magnitude=80.0, quality=30.0)
    assert r2.should_trigger(m_threshold=70, q_threshold=60) is False


def test_movement_result_cooldown_seconds():
    assert MovementResult(magnitude=75.0, quality=50.0).cooldown_seconds == 1800  # 30min
    assert MovementResult(magnitude=85.0, quality=50.0).cooldown_seconds == 600   # 10min
    assert MovementResult(magnitude=95.0, quality=50.0).cooldown_seconds == 180   # 3min


class TestMovementDataGuard:
    """Movement should output noise when data is insufficient or stale."""

    def _setup_monitored_event(self, db):
        upsert_event(EventRow(
            event_id="ev1", title="Test", market_type="crypto", updated_at="now",
        ), db)
        upsert_market(MarketRow(
            market_id="m1", event_id="ev1", question="Q",
            clob_token_id_yes="tok1", yes_price=0.50, no_price=0.50,
            best_bid=0.49, best_ask=0.51, spread=0.02,
            bid_depth=1000, ask_depth=1000,
            updated_at="now",
        ), db)
        upsert_event_monitor("ev1", auto_monitor=True, db=db)

    def test_cold_start_writes_noise(self, db):
        """No movement_log history → should write noise, not compute signals."""
        from scanner.daemon.poll_job import _run_intelligence_layer

        self._setup_monitored_event(db)
        _run_intelligence_layer(db)

        rows = db.conn.execute("SELECT label FROM movement_log WHERE market_id = 'm1'").fetchall()
        assert len(rows) == 1
        assert rows[0]["label"] == "noise"

    def test_insufficient_data_writes_noise(self, db):
        """Less than MIN_HISTORY entries → noise."""
        from scanner.daemon.poll_job import _run_intelligence_layer

        self._setup_monitored_event(db)
        # Add only 2 entries (less than threshold)
        for i in range(2):
            append_movement(event_id="ev1", market_id="m1",
                yes_price=0.50, magnitude=0, quality=0, label="noise", db=db)
        db.conn.commit()

        _run_intelligence_layer(db)

        rows = db.conn.execute(
            "SELECT label, magnitude FROM movement_log WHERE market_id = 'm1' ORDER BY id DESC LIMIT 1"
        ).fetchall()
        assert rows[0]["label"] == "noise"
        assert rows[0]["magnitude"] == 0

    def test_stale_data_writes_noise(self, db):
        """Old movement_log entries (> staleness threshold) → noise even with big price gap."""
        from scanner.daemon.poll_job import _run_intelligence_layer

        self._setup_monitored_event(db)
        # Insert 10 entries but all 15 min ago, with varying prices around 0.30
        old_ts = (datetime.now(UTC) - timedelta(minutes=15)).isoformat()
        for i in range(10):
            price = 0.28 + i * 0.004  # 0.28 to 0.316
            db.conn.execute(
                """INSERT INTO movement_log
                (event_id, market_id, created_at, yes_price, magnitude, quality, label)
                VALUES (?, ?, ?, ?, 0, 0, 'noise')""",
                ("ev1", "m1", old_ts, price),
            )
        db.conn.commit()

        # Current price is 0.70 — huge gap, but data is stale so should be noise
        db.conn.execute("UPDATE markets SET yes_price = 0.70 WHERE market_id = 'm1'")
        db.conn.commit()

        _run_intelligence_layer(db)

        rows = db.conn.execute(
            "SELECT label, magnitude FROM movement_log WHERE market_id = 'm1' ORDER BY id DESC LIMIT 1"
        ).fetchall()
        assert rows[0]["label"] == "noise"
        assert rows[0]["magnitude"] == 0

    def test_sufficient_fresh_data_computes_signals(self, db):
        """Enough recent entries → should compute real signals (not all zero)."""
        from scanner.daemon.poll_job import _run_intelligence_layer

        self._setup_monitored_event(db)
        # Add enough recent entries with varying prices
        now = datetime.now(UTC)
        for i in range(10):
            ts = (now - timedelta(seconds=30 * (10 - i))).isoformat()
            price = 0.45 + i * 0.01  # increasing from 0.45 to 0.54
            db.conn.execute(
                """INSERT INTO movement_log
                (event_id, market_id, created_at, yes_price, magnitude, quality, label)
                VALUES (?, ?, ?, ?, 0, 0, 'noise')""",
                ("ev1", "m1", ts, price),
            )
        db.conn.commit()

        # Current price significantly different from history
        db.conn.execute("UPDATE markets SET yes_price = 0.65 WHERE market_id = 'm1'")
        db.conn.commit()

        _run_intelligence_layer(db)

        rows = db.conn.execute(
            "SELECT magnitude FROM movement_log WHERE market_id = 'm1' ORDER BY id DESC LIMIT 1"
        ).fetchall()
        # With a big price jump (0.45-0.54 history → 0.65 current), magnitude should be > 0
        assert rows[0]["magnitude"] > 0
