"""Tests for movement → AI trigger logic."""


import pytest

from polily.core.config import MovementConfig
from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.monitor_store import upsert_event_monitor
from polily.daemon.poll_job import _check_event_trigger
from polily.monitor.store import append_movement, get_today_analysis_count


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed(db, event_id="ev1", n_markets=2):
    upsert_event(EventRow(event_id=event_id, title="BTC", updated_at="now"), db)
    markets = []
    for i in range(n_markets):
        mr = MarketRow(
            market_id=f"m{i}", event_id=event_id, question=f"Q{i}",
            clob_token_id_yes=f"tok{i}", yes_price=0.5, updated_at="now",
        )
        upsert_market(mr, db)
        markets.append(mr)
    upsert_event_monitor(event_id, auto_monitor=True, db=db)
    return markets


def _write_movement(db, event_id="ev1", market_id="m0",
                    magnitude=0, quality=0, label="noise",
                    triggered=False):
    append_movement(
        event_id=event_id, market_id=market_id,
        yes_price=0.5, magnitude=magnitude, quality=quality,
        label=label, triggered_analysis=triggered, db=db,
    )
    db.conn.commit()


class TestCheckEventTrigger:
    def test_no_trigger_below_threshold(self, db):
        markets = _seed(db)
        mc = MovementConfig()
        _write_movement(db, magnitude=50, quality=40)  # below threshold
        _check_event_trigger("ev1", markets, mc, db)

        assert get_today_analysis_count("ev1", db) == 0

    def test_trigger_above_threshold(self, db):
        markets = _seed(db)
        mc = MovementConfig()
        _write_movement(db, magnitude=80, quality=70)  # above threshold

        # No scheduler context, so trigger will log but not submit job
        # But it should mark triggered_analysis = 1
        _check_event_trigger("ev1", markets, mc, db)
        db.conn.commit()

        row = db.conn.execute(
            "SELECT triggered_analysis FROM movement_log ORDER BY id DESC LIMIT 1",
        ).fetchone()
        assert row["triggered_analysis"] == 1

    def test_marks_spike_row_not_temporally_latest_row(self, db):
        """v0.12.0 backlog #2 — observability fix for dispatcher/scorer label mismatch.

        Surfaced by NarrativeWriter dev_feedback 2026-05-10 09:49 CST:
            "Movement-mode dispatch but recent movement_log rows all noise-labeled
             with triggered_analysis=0; possible threshold/label mismatch in scorer."

        Root cause: the UPDATE that marks triggered_analysis=1 uses
        `ORDER BY created_at DESC LIMIT 1` — it picks the temporally-latest
        movement_log row for the event regardless of which row actually
        crossed the trigger threshold. When a tick writes multiple sub-market
        rows microseconds apart (one with M=80 Q=70 = spike, another with
        M=10 Q=10 = baseline noise), the marker can land on the noise row
        if it happens to be inserted LAST chronologically.

        Result: agent's query "which row triggered this dispatch?" finds
        a noise-labeled row marked triggered_analysis=1 — confusing
        provenance signal.

        Fix: UPDATE should pick the row with the highest magnitude (the
        actual spike that drove the trigger), not the temporal latest.
        """
        markets = _seed(db, n_markets=2)
        mc = MovementConfig()

        # Insert SPIKE row first (m0), then NOISE row last (m1) so temporal
        # ordering would mark the wrong row under the old logic.
        _write_movement(db, market_id="m0", magnitude=85, quality=75, label="consensus")
        _write_movement(db, market_id="m1", magnitude=5, quality=5, label="noise")

        _check_event_trigger("ev1", markets, mc, db)
        db.conn.commit()

        # Spike row (m0) should be marked, not the temporal latest (m1)
        rows = db.conn.execute(
            "SELECT market_id, magnitude, triggered_analysis "
            "FROM movement_log ORDER BY id"
        ).fetchall()
        marked = [(r["market_id"], r["magnitude"]) for r in rows
                  if r["triggered_analysis"] == 1]
        assert len(marked) == 1, f"Exactly one row should be marked; got {marked}"
        assert marked[0][0] == "m0", (
            f"Spike row (m0, M=85) should be marked; instead {marked[0][0]} "
            f"(M={marked[0][1]}) got the flag. The UPDATE is picking by "
            f"created_at DESC instead of magnitude DESC."
        )

    def test_cooldown_prevents_retrigger(self, db):
        markets = _seed(db)
        mc = MovementConfig()

        # First trigger
        _write_movement(db, magnitude=85, quality=75, triggered=True)

        # Second high movement immediately after
        _write_movement(db, magnitude=80, quality=70)
        _check_event_trigger("ev1", markets, mc, db)
        db.conn.commit()

        # Should NOT trigger again (cooldown)
        triggered_count = db.conn.execute(
            "SELECT COUNT(*) FROM movement_log WHERE triggered_analysis = 1",
        ).fetchone()[0]
        assert triggered_count == 1  # only the first one

    def test_daily_limit(self, db):
        markets = _seed(db)
        mc = MovementConfig(daily_analysis_limit=2)

        # Simulate 2 already triggered today
        _write_movement(db, magnitude=80, quality=70, triggered=True)
        _write_movement(db, magnitude=85, quality=75, triggered=True)

        # Third high movement
        _write_movement(db, magnitude=90, quality=80)
        _check_event_trigger("ev1", markets, mc, db)
        db.conn.commit()

        triggered_count = db.conn.execute(
            "SELECT COUNT(*) FROM movement_log WHERE triggered_analysis = 1",
        ).fetchone()[0]
        assert triggered_count == 2  # not 3

    def test_event_level_aggregation(self, db):
        """Max M from one market + max Q from another → trigger."""
        markets = _seed(db, n_markets=2)
        mc = MovementConfig()

        # m0 has high M, m1 has high Q — individually neither triggers
        _write_movement(db, market_id="m0", magnitude=75, quality=30)
        _write_movement(db, market_id="m1", magnitude=20, quality=65)
        _check_event_trigger("ev1", markets, mc, db)
        db.conn.commit()

        row = db.conn.execute(
            "SELECT COUNT(*) FROM movement_log WHERE triggered_analysis = 1",
        ).fetchone()[0]
        assert row == 1  # event-level aggregation triggered
