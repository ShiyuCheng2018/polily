"""Service-layer guard: disabling monitor on an event with open positions
must fail — closing monitoring would silently abandon the user's position
(no more polling → no auto-resolution → unresolved skin-in-the-game)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from polily.core.monitor_store import get_event_monitor, upsert_event_monitor
from polily.tui.service import PolilyService


def _service() -> PolilyService:
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    tmp = tempfile.TemporaryDirectory()
    db = PolilyDB(Path(tmp.name) / "t.db")
    svc = PolilyService(config=cfg, db=db)
    svc._tmp = tmp
    return svc


def _seed_open_event_with_position(svc, event_id="ev1", market_id="m1", side="yes"):
    upsert_event(EventRow(event_id=event_id, title="E", updated_at="now"), svc.db)
    upsert_market(
        MarketRow(market_id=market_id, event_id=event_id, question="Q", updated_at="now"),
        svc.db,
    )
    upsert_event_monitor(event_id, auto_monitor=True, db=svc.db)
    svc.db.conn.execute(
        "INSERT INTO positions (event_id, market_id, side, shares, avg_cost, "
        "cost_basis, title, opened_at, updated_at) "
        "VALUES (?, ?, ?, 10.0, 0.5, 5.0, 'Q', 'now', 'now')",
        (event_id, market_id, side),
    )
    svc.db.conn.commit()


def _seed_open_event_no_position(svc, event_id="ev1", market_id="m1"):
    upsert_event(EventRow(event_id=event_id, title="E", updated_at="now"), svc.db)
    upsert_market(
        MarketRow(market_id=market_id, event_id=event_id, question="Q", updated_at="now"),
        svc.db,
    )
    upsert_event_monitor(event_id, auto_monitor=True, db=svc.db)


class TestTogglePositionGuard:
    def test_disable_with_position_raises(self):
        from polily.tui.service import ActivePositionsError

        svc = _service()
        _seed_open_event_with_position(svc)

        with pytest.raises(ActivePositionsError):
            svc.toggle_monitor("ev1", enable=False)

        # State must NOT have changed — auto_monitor still 1
        assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 1

    def test_disable_without_position_succeeds(self):
        svc = _service()
        _seed_open_event_no_position(svc)

        svc.toggle_monitor("ev1", enable=False)

        assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 0

    def test_enable_with_position_succeeds(self):
        """The guard only fires on disable — enabling is always allowed."""
        svc = _service()
        _seed_open_event_with_position(svc)
        # Start from disabled
        upsert_event_monitor("ev1", auto_monitor=False, db=svc.db)

        svc.toggle_monitor("ev1", enable=True)

        assert get_event_monitor("ev1", svc.db)["auto_monitor"] == 1


class TestEventPositionCount:
    def test_zero_when_no_positions(self):
        svc = _service()
        _seed_open_event_no_position(svc)

        assert svc.get_event_position_count("ev1") == 0

    def test_counts_yes_and_no_separately(self):
        svc = _service()
        _seed_open_event_with_position(svc, side="yes")
        # Add a second position row on the NO side (YES + NO coexist)
        svc.db.conn.execute(
            "INSERT INTO positions (event_id, market_id, side, shares, avg_cost, "
            "cost_basis, title, opened_at, updated_at) "
            "VALUES ('ev1', 'm1', 'no', 5.0, 0.5, 2.5, 'Q', 'now', 'now')",
        )
        svc.db.conn.commit()

        assert svc.get_event_position_count("ev1") == 2
