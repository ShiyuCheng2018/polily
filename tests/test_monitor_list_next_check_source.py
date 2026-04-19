"""下次检查 column must come from scan_logs pending rows (not event_monitors).

Task 12 (v0.7.0): `event_monitors.next_check_at` / `next_check_reason` were
dropped in Task 1. The monitor list's `下次检查` column now reads the earliest
pending scan_logs row per event via LEFT JOIN subquery.
"""
from unittest.mock import MagicMock

import pytest

from scanner.core.db import PolilyDB
from scanner.core.monitor_store import upsert_event_monitor
from scanner.scan_log import insert_pending_scan
from scanner.tui.service import ScanService
from tests.conftest import make_event, setup_event_and_market


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    db = PolilyDB(tmp_path / "t.db")
    # Seed two events with markets so the main query returns both.
    setup_event_and_market(db, event_id="ev1", market_id="m-ev1")
    setup_event_and_market(db, event_id="ev2", market_id="m-ev2")
    # Override titles
    from scanner.core.event_store import upsert_event
    upsert_event(make_event(event_id="ev1", title="Iran hormuz"), db)
    upsert_event(make_event(event_id="ev2", title="BTC > 100k"), db)
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    upsert_event_monitor("ev2", auto_monitor=True, db=db)
    s = ScanService(config=cfg, db=db)
    yield s
    db.close()


def test_query_events_reads_next_check_from_scan_logs(svc):
    """`next_check_at` in returned dict comes from scan_logs pending MIN(scheduled_at)."""
    insert_pending_scan(
        event_id="ev1", event_title="Iran hormuz",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="FOMC", db=svc.db,
    )
    rows = svc.get_all_events()
    row_iran = next(r for r in rows if r["event"].event_id == "ev1")
    row_btc = next(r for r in rows if r["event"].event_id == "ev2")
    assert row_iran["next_check_at"] == "2026-05-01T10:00:00+00:00"
    assert row_btc["next_check_at"] is None


def test_query_events_picks_earliest_pending(svc):
    """Two pending rows for the same event → take earliest scheduled_at."""
    insert_pending_scan(
        event_id="ev1", event_title="Iran hormuz",
        scheduled_at="2026-06-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="later", db=svc.db,
    )
    insert_pending_scan(
        event_id="ev1", event_title="Iran hormuz",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason="sooner", db=svc.db,
    )
    rows = svc.get_all_events()
    row_iran = next(r for r in rows if r["event"].event_id == "ev1")
    assert row_iran["next_check_at"] == "2026-05-01T10:00:00+00:00"
