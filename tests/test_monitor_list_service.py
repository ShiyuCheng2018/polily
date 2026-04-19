"""Service-layer contract for the Watchlist view: per-event movement + AI version."""

from unittest.mock import MagicMock

import pytest

from scanner.monitor.store import append_movement
from scanner.tui.service import ScanService
from tests.conftest import setup_event_and_market


def _service(db) -> ScanService:
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    return ScanService(config=cfg, db=db)


@pytest.fixture
def db_with_two_events(polily_db):
    setup_event_and_market(polily_db, event_id="evA", market_id="mA", question="Event A")
    setup_event_and_market(polily_db, event_id="evB", market_id="mB", question="Event B")
    polily_db.conn.commit()
    return polily_db


class TestAnalysisVersionField:
    def test_zero_analyses_returns_zero_count(self, db_with_two_events):
        service = _service(db_with_two_events)
        events = service.get_all_events()
        assert all("analysis_count" in e for e in events)
        assert all(e["analysis_count"] == 0 for e in events)

    def test_counts_analysis_rows(self, db_with_two_events):
        db = db_with_two_events
        db.conn.execute(
            "INSERT INTO analyses (event_id, version, created_at, narrative_output) "
            "VALUES ('evA', 1, '2026-04-19T00:00:00', '{}')"
        )
        db.conn.execute(
            "INSERT INTO analyses (event_id, version, created_at, narrative_output) "
            "VALUES ('evA', 2, '2026-04-19T00:01:00', '{}')"
        )
        db.conn.commit()

        service = _service(db)
        events = {e["event"].event_id: e for e in service.get_all_events()}
        assert events["evA"]["analysis_count"] == 2
        assert events["evB"]["analysis_count"] == 0


class TestMovementField:
    def test_no_movement_row_means_movement_none(self, db_with_two_events):
        service = _service(db_with_two_events)
        events = service.get_all_events()
        assert all("movement" in e for e in events)
        assert all(e["movement"] is None for e in events)

    def test_latest_movement_row_surfaced(self, db_with_two_events):
        db = db_with_two_events
        append_movement(
            event_id="evA", market_id="mA",
            yes_price=0.6, magnitude=72.0, quality=85.0, label="consensus", db=db,
        )
        db.conn.commit()

        service = _service(db)
        events = {e["event"].event_id: e for e in service.get_all_events()}

        mov = events["evA"]["movement"]
        assert mov is not None
        assert mov["label"] == "consensus"
        assert mov["magnitude"] == pytest.approx(72.0)
        assert mov["quality"] == pytest.approx(85.0)

        assert events["evB"]["movement"] is None
