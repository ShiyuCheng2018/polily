"""Tests for APScheduler-based watch scheduler."""

from datetime import UTC, datetime, timedelta

from scanner.core.monitor_store import upsert_event_monitor
from scanner.daemon.scheduler import WatchScheduler


def test_schedule_and_list(polily_db):
    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    future = datetime.now(UTC) + timedelta(hours=1)
    scheduler.schedule("0xabc", future)
    pending = scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0]["market_id"] == "0xabc"
    scheduler.shutdown()


def test_cancel(polily_db):
    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    future = datetime.now(UTC) + timedelta(hours=1)
    scheduler.schedule("0xabc", future)
    assert len(scheduler.list_pending()) == 1
    scheduler.cancel("0xabc")
    assert len(scheduler.list_pending()) == 0
    scheduler.shutdown()


def test_cancel_nonexistent_does_not_raise(polily_db):
    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    scheduler.cancel("0xnonexistent")
    scheduler.shutdown()


def test_replace_existing(polily_db):
    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    t1 = datetime.now(UTC) + timedelta(hours=1)
    t2 = datetime.now(UTC) + timedelta(hours=2)
    scheduler.schedule("0xabc", t1)
    scheduler.schedule("0xabc", t2)
    pending = scheduler.list_pending()
    assert len(pending) == 1
    scheduler.shutdown()


def _seed_event(db, event_id: str):
    """Insert a dummy event row for FK constraints."""
    now = datetime.now(UTC).isoformat()
    db.conn.execute(
        "INSERT OR IGNORE INTO events (event_id, title, updated_at) VALUES (?, ?, ?)",
        (event_id, f"Event {event_id}", now),
    )
    db.conn.commit()


def test_restore_from_db(polily_db):
    from scanner.core.monitor_store import update_next_check_at

    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    # Event with auto_monitor + next_check_at
    _seed_event(polily_db, "0x1")
    upsert_event_monitor("0x1", auto_monitor=True, db=polily_db)
    update_next_check_at("0x1", future, "test", polily_db)

    # Event without auto_monitor
    _seed_event(polily_db, "0x2")
    upsert_event_monitor("0x2", auto_monitor=False, db=polily_db)

    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    scheduler.restore_from_db()
    pending = scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0]["market_id"] == "0x1"
    scheduler.shutdown()


def test_restore_overdue_schedules_immediately(polily_db):
    from scanner.core.monitor_store import update_next_check_at

    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    _seed_event(polily_db, "0x1")
    upsert_event_monitor("0x1", auto_monitor=True, db=polily_db)
    update_next_check_at("0x1", past, "test", polily_db)

    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    scheduler.restore_from_db()
    scheduler.shutdown()
