"""PolilyService.get_archived_events — events the user was monitoring when
they closed. Filter: events.closed=1 AND event_monitors.auto_monitor=1."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import PolilyService


def _service() -> PolilyService:
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    cfg.wallet.starting_balance = 100.0
    tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(tmp.name) / "t.db")
    svc = PolilyService(config=cfg, db=db)
    svc._tmp = tmp
    return svc


def _seed_event(svc, event_id: str, title: str, closed: bool, auto_monitor: bool,
                score: float = 70.0, updated_at: str = "2026-04-19T00:00:00"):
    upsert_event(
        EventRow(event_id=event_id, title=title, closed=int(closed), updated_at=updated_at),
        svc.db,
    )
    svc.db.conn.execute(
        "UPDATE events SET structure_score=? WHERE event_id=?", (score, event_id),
    )
    upsert_market(
        MarketRow(market_id=f"m-{event_id}", event_id=event_id, question="Q",
                  updated_at=updated_at),
        svc.db,
    )
    upsert_event_monitor(event_id, auto_monitor=auto_monitor, db=svc.db)
    svc.db.conn.commit()


class TestGetArchivedEvents:
    def test_empty_db_returns_empty_list(self):
        svc = _service()
        assert svc.get_archived_events() == []

    def test_monitored_but_not_closed_not_returned(self):
        svc = _service()
        _seed_event(svc, "evA", "Still open", closed=False, auto_monitor=True)
        assert svc.get_archived_events() == []

    def test_closed_but_not_monitored_not_returned(self):
        """User toggled monitoring off BEFORE event closed — not archivable."""
        svc = _service()
        _seed_event(svc, "evA", "Closed but opted out", closed=True, auto_monitor=False)
        assert svc.get_archived_events() == []

    def test_closed_and_monitored_returned(self):
        svc = _service()
        _seed_event(svc, "evA", "Monitored then closed", closed=True, auto_monitor=True)

        results = svc.get_archived_events()
        assert len(results) == 1
        assert results[0]["event"].event_id == "evA"
        assert results[0]["event"].title == "Monitored then closed"

    def test_results_include_market_count(self):
        svc = _service()
        _seed_event(svc, "evA", "E", closed=True, auto_monitor=True)
        # Add a second market to evA
        upsert_market(
            MarketRow(market_id="m-evA-2", event_id="evA", question="Q2",
                      updated_at="2026-04-19T00:00:00"),
            svc.db,
        )
        svc.db.conn.commit()

        results = svc.get_archived_events()
        assert results[0]["market_count"] == 2

    def test_results_sorted_by_updated_at_desc(self):
        svc = _service()
        _seed_event(svc, "old", "Old close", closed=True, auto_monitor=True,
                    updated_at="2026-01-01T00:00:00")
        _seed_event(svc, "new", "Recent close", closed=True, auto_monitor=True,
                    updated_at="2026-04-19T00:00:00")

        results = svc.get_archived_events()
        assert [r["event"].event_id for r in results] == ["new", "old"]
