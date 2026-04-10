"""Tests for APScheduler-based watch scheduler."""

from datetime import UTC, datetime, timedelta

from scanner.daemon.scheduler import WatchScheduler
from scanner.market_state import MarketState, set_market_state


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


def test_restore_from_db(polily_db):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    set_market_state("0x1", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=True, next_check_at=future,
    ), polily_db)
    set_market_state("0x2", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=False,
    ), polily_db)
    set_market_state("0x3", MarketState(
        status="pass", updated_at="2026-04-01T10:00:00",
    ), polily_db)

    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    scheduler.restore_from_db()
    pending = scheduler.list_pending()
    assert len(pending) == 1
    assert pending[0]["market_id"] == "0x1"
    scheduler.shutdown()


def test_restore_overdue_schedules_immediately(polily_db):
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    set_market_state("0x1", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=True, next_check_at=past,
    ), polily_db)

    scheduler = WatchScheduler(polily_db)
    scheduler.start()
    scheduler.restore_from_db()
    scheduler.shutdown()
