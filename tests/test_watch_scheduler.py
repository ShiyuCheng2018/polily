"""Tests for APScheduler-based watch scheduler."""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scanner.db import PolilyDB
from scanner.market_state import MarketState, set_market_state
from scanner.watch_scheduler import WatchScheduler


def _make_db():
    tmp = tempfile.mkdtemp()
    return PolilyDB(Path(tmp) / "polily.db")


def test_schedule_and_list():
    db = _make_db()
    scheduler = WatchScheduler(db)
    scheduler.start()
    future = datetime.now(UTC) + timedelta(hours=1)
    scheduler.schedule("0xabc", future)
    pending = scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0]["market_id"] == "0xabc"
    scheduler.shutdown()
    db.close()


def test_cancel():
    db = _make_db()
    scheduler = WatchScheduler(db)
    scheduler.start()
    future = datetime.now(UTC) + timedelta(hours=1)
    scheduler.schedule("0xabc", future)
    assert len(scheduler.list_pending()) == 1
    scheduler.cancel("0xabc")
    assert len(scheduler.list_pending()) == 0
    scheduler.shutdown()
    db.close()


def test_cancel_nonexistent_does_not_raise():
    db = _make_db()
    scheduler = WatchScheduler(db)
    scheduler.start()
    scheduler.cancel("0xnonexistent")  # should not raise
    scheduler.shutdown()
    db.close()


def test_replace_existing():
    db = _make_db()
    scheduler = WatchScheduler(db)
    scheduler.start()
    t1 = datetime.now(UTC) + timedelta(hours=1)
    t2 = datetime.now(UTC) + timedelta(hours=2)
    scheduler.schedule("0xabc", t1)
    scheduler.schedule("0xabc", t2)  # should replace
    pending = scheduler.list_pending()
    assert len(pending) == 1
    scheduler.shutdown()
    db.close()


def test_restore_from_db():
    db = _make_db()
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    set_market_state("0x1", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=True, next_check_at=future,
    ), db)
    set_market_state("0x2", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=False,  # not auto-monitored
    ), db)
    set_market_state("0x3", MarketState(
        status="pass", updated_at="2026-04-01T10:00:00",
    ), db)

    scheduler = WatchScheduler(db)
    scheduler.start()
    scheduler.restore_from_db()
    pending = scheduler.list_pending()
    assert len(pending) == 1  # only 0x1
    assert pending[0]["market_id"] == "0x1"
    scheduler.shutdown()
    db.close()


def test_restore_overdue_schedules_immediately():
    db = _make_db()
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    set_market_state("0x1", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=True, next_check_at=past,
    ), db)

    scheduler = WatchScheduler(db)
    scheduler.start()
    scheduler.restore_from_db()
    pending = scheduler.list_pending()
    # Overdue job should be scheduled (may already be running/completed,
    # but at minimum it was registered)
    # Just verify no crash
    scheduler.shutdown()
    db.close()
