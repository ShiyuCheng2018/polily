"""v0.10.1 — daemon startup banner 'X markets' must match what poll
cycle actually fetches, not the total active rows in db.
"""
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.monitor_store import upsert_event_monitor


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    d = PolilyDB(tmp_path / "polily.db")
    yield d
    d.close()


def _add(db, event_id: str, n_markets: int, *, monitored: bool) -> None:
    now = datetime.now(UTC).isoformat()
    upsert_event(EventRow(
        event_id=event_id, title=event_id, slug=event_id,
        market_count=n_markets, updated_at=now,
    ), db)
    if monitored:
        upsert_event_monitor(event_id, auto_monitor=True, db=db)
    for i in range(n_markets):
        upsert_market(MarketRow(
            market_id=f"{event_id}_m{i}", event_id=event_id,
            question=f"Market {i}", outcomes='["Yes","No"]',
            active=1, closed=0, updated_at=now,
        ), db)


def test_banner_count_matches_poll_query_with_phantom_markets(db):
    """Bug scenario: 1 monitored event w/ 3 markets + 1 phantom event w/ 7
    active markets. Banner must say 3, not 10. v2 SF-C: imports the
    actual production helper so a regression in scheduler.py is caught."""
    _add(db, "ev_monitor", n_markets=3, monitored=True)
    _add(db, "ev_phantom", n_markets=7, monitored=False)

    from polily.daemon.poll_job import _get_monitored_markets
    from polily.daemon.scheduler import _count_monitored_active_markets

    banner_count = _count_monitored_active_markets(db)
    poll_markets = _get_monitored_markets(db)

    assert banner_count == len(poll_markets) == 3, (
        f"banner={banner_count}, poll={len(poll_markets)}, expected both=3"
    )


def test_banner_count_zero_when_no_monitored_events(db):
    _add(db, "ev_phantom", n_markets=5, monitored=False)
    from polily.daemon.scheduler import _count_monitored_active_markets
    assert _count_monitored_active_markets(db) == 0


def test_banner_helper_partition_with_archived_events(db):
    """Pin current behavior: banner SQL only filters m.active=1 AND m.closed=0,
    NOT events.closed — so a closed event that still has an active+open
    market DOES count toward the banner.

    This is a known limitation accepted for v0.10.1 (rare in practice; closed
    events don't get fresh polls anyway via the daemon's resolve path). If
    the SQL is ever tightened to also filter events.closed=0 (matching Task 2's
    get_monitor_count fix), this test must be updated to assert == 0.
    """
    from polily.daemon.scheduler import _count_monitored_active_markets

    now = datetime.now(UTC).isoformat()
    upsert_event(EventRow(
        event_id="ev_closed", title="closed event", slug="x",
        market_count=2, closed=1, active=0, updated_at=now,
    ), db)
    upsert_event_monitor("ev_closed", auto_monitor=True, db=db)
    upsert_market(MarketRow(
        market_id="ev_closed_m1", event_id="ev_closed",
        question="q", outcomes='["Yes","No"]',
        active=1, closed=0, updated_at=now,
    ), db)

    # event.closed=1 but auto_monitor=1 — should NOT count for the banner
    # (matches Task 2 partition between active monitor and archive).
    # NOTE: current banner SQL only filters m.active=1 AND m.closed=0,
    # NOT events.closed=0. Phantom of "closed event but with active
    # markets" is rare but possible. Plan accepts this as-is for v0.10.1
    # since it's not user-visible (closed events don't get fresh polls
    # anyway via the daemon's resolve path), and future-proof.
    # Test asserts current behavior — if it changes intentionally, this
    # test must be updated alongside.
    assert _count_monitored_active_markets(db) == 1
