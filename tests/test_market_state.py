"""Tests for SQLite-backed market state."""

from scanner.market_state import (
    MarketState,
    get_auto_monitor_watches,
    get_market_state,
    get_watched_markets,
    is_passed,
    set_market_state,
)


def test_set_and_get(polily_db):
    state = MarketState(
        status="watch",
        updated_at="2026-04-01T10:00:00",
        title="BTC 68000",
        next_check_at="2026-04-05T20:00:00",
        watch_reason="tariff announcement expected",
        watch_sequence=0,
        price_at_watch=0.65,
        auto_monitor=True,
    )
    set_market_state("0xabc", state, polily_db)
    loaded = get_market_state("0xabc", polily_db)
    assert loaded is not None
    assert loaded.status == "watch"
    assert loaded.title == "BTC 68000"
    assert loaded.next_check_at == "2026-04-05T20:00:00"
    assert loaded.watch_reason == "tariff announcement expected"
    assert loaded.price_at_watch == 0.65
    assert loaded.auto_monitor is True


def test_get_nonexistent(polily_db):
    assert get_market_state("0xnonexistent", polily_db) is None


def test_upsert(polily_db):
    set_market_state("0xabc", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00", title="V1",
    ), polily_db)
    set_market_state("0xabc", MarketState(
        status="pass", updated_at="2026-04-02T10:00:00", title="V2",
    ), polily_db)
    loaded = get_market_state("0xabc", polily_db)
    assert loaded.status == "pass"
    assert loaded.title == "V2"


def test_all_statuses(polily_db):
    for status in ("buy_yes", "buy_no", "watch", "pass", "closed"):
        set_market_state(f"0x{status}", MarketState(
            status=status, updated_at="2026-04-01T10:00:00",
        ), polily_db)
        loaded = get_market_state(f"0x{status}", polily_db)
        assert loaded.status == status


def test_get_watched_markets(polily_db):
    set_market_state("0x1", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
    ), polily_db)
    set_market_state("0x2", MarketState(
        status="pass", updated_at="2026-04-01T10:00:00",
    ), polily_db)
    set_market_state("0x3", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
    ), polily_db)
    watched = get_watched_markets(polily_db)
    assert len(watched) == 2
    assert "0x1" in watched
    assert "0x3" in watched
    assert "0x2" not in watched


def test_get_auto_monitor_watches(polily_db):
    set_market_state("0x1", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=True, next_check_at="2026-04-05T20:00:00",
    ), polily_db)
    set_market_state("0x2", MarketState(
        status="watch", updated_at="2026-04-01T10:00:00",
        auto_monitor=False,
    ), polily_db)
    result = get_auto_monitor_watches(polily_db)
    assert len(result) == 1
    assert "0x1" in result


def test_is_passed(polily_db):
    set_market_state("0xabc", MarketState(
        status="pass", updated_at="2026-04-01T10:00:00",
    ), polily_db)
    assert is_passed("0xabc", polily_db) is True
    assert is_passed("0xnonexistent", polily_db) is False


def test_watch_conditions_stored(polily_db):
    state = MarketState(
        status="watch",
        updated_at="2026-04-01T10:00:00",
        wc_watch_reason="structure good but no edge",
        wc_better_entry="YES <= 0.50",
        wc_trigger_event="BTC drops to 65k",
        wc_invalidation="< 12h to resolution",
    )
    set_market_state("0xabc", state, polily_db)
    loaded = get_market_state("0xabc", polily_db)
    assert loaded.wc_watch_reason == "structure good but no edge"
    assert loaded.wc_better_entry == "YES <= 0.50"
    assert loaded.wc_trigger_event == "BTC drops to 65k"
    assert loaded.wc_invalidation == "< 12h to resolution"


def test_resolution_time_stored(polily_db):
    set_market_state("0xabc", MarketState(
        status="watch",
        updated_at="2026-04-01T10:00:00",
        resolution_time="2026-04-10T00:00:00",
    ), polily_db)
    loaded = get_market_state("0xabc", polily_db)
    assert loaded.resolution_time == "2026-04-10T00:00:00"
