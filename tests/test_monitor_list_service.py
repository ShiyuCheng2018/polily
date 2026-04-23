"""Service-layer contract for the Watchlist view: per-event movement + AI version."""

from unittest.mock import MagicMock

import pytest

from polily.monitor.store import append_movement
from polily.tui.service import PolilyService
from tests.conftest import setup_event_and_market


def _service(db) -> PolilyService:
    cfg = MagicMock()
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    return PolilyService(config=cfg, db=db)


@pytest.fixture
def db_with_two_events(polily_db):
    from polily.core.monitor_store import upsert_event_monitor

    setup_event_and_market(polily_db, event_id="evA", market_id="mA", question="Event A")
    setup_event_and_market(polily_db, event_id="evB", market_id="mB", question="Event B")
    # Movement is only fetched for monitored events (Watchlist-only concern).
    upsert_event_monitor(event_id="evA", auto_monitor=True, db=polily_db)
    upsert_event_monitor(event_id="evB", auto_monitor=True, db=polily_db)
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

    def test_poll_tick_shape_ignores_aggregate_row(self, db_with_two_events):
        """Regression: a real poll tick writes per-market rows first then an
        event-level aggregate row with market_id=NULL and M=0/Q=0/label=noise
        (see poll_job._write_movement_log). A naive MAX(id) picks the aggregate
        and reports '平静 M:0 Q:0' no matter how much the sub-markets moved.
        The Watchlist must surface the strongest per-market row instead.
        """
        db = db_with_two_events
        # Per-market rows (real signal)
        append_movement(
            event_id="evA", market_id="mA",
            yes_price=0.6, magnitude=72.0, quality=85.0, label="consensus", db=db,
        )
        append_movement(
            event_id="evA", market_id="mA2",
            yes_price=0.5, magnitude=30.0, quality=40.0, label="slow_build", db=db,
        )
        # Event-level aggregate row written last — the bug trigger
        append_movement(
            event_id="evA", market_id=None,
            magnitude=0.0, quality=0.0, label="noise", db=db,
        )
        db.conn.commit()

        service = _service(db)
        events = {e["event"].event_id: e for e in service.get_all_events()}

        mov = events["evA"]["movement"]
        assert mov is not None
        # Must surface the strong per-market row, not the NULL aggregate
        assert mov["label"] == "consensus"
        assert mov["magnitude"] == pytest.approx(72.0)
        assert mov["quality"] == pytest.approx(85.0)

    def test_settlement_end_dates_surfaced(self, db_with_two_events):
        """`_query_events` must return MIN/MAX end_date across non-closed markets
        so the Watchlist can render a settlement-window column."""
        db = db_with_two_events
        # Add a second market to evA with a later end_date
        from polily.core.event_store import MarketRow, upsert_market

        upsert_market(
            MarketRow(
                market_id="mA2", event_id="evA", question="second market",
                end_date="2027-06-01T00:00:00+00:00", closed=0,
                updated_at="2026-04-19T00:00:00",
            ),
            db,
        )
        # evA's original market mA got end_date via setup — check & force to
        # an earlier date
        db.conn.execute(
            "UPDATE markets SET end_date = ? WHERE market_id = ?",
            ("2027-01-01T00:00:00+00:00", "mA"),
        )
        db.conn.commit()

        service = _service(db)
        events = {e["event"].event_id: e for e in service.get_all_events()}

        assert events["evA"]["markets_end_min"] == "2027-01-01T00:00:00+00:00"
        assert events["evA"]["markets_end_max"] == "2027-06-01T00:00:00+00:00"

    def test_only_aggregate_rows_returns_noise_zero(self, db_with_two_events):
        """If every row so far this hour is an aggregate (market_id=NULL),
        surface (noise, 0, 0) — matches existing movement_sparkline semantics."""
        db = db_with_two_events
        append_movement(
            event_id="evA", market_id=None,
            magnitude=0.0, quality=0.0, label="noise", db=db,
        )
        db.conn.commit()

        service = _service(db)
        events = {e["event"].event_id: e for e in service.get_all_events()}
        mov = events["evA"]["movement"]
        # We have movement data (not None), but the rolled-up signal is calm
        assert mov is not None
        assert mov["label"] == "noise"
        assert mov["magnitude"] == pytest.approx(0.0)
        assert mov["quality"] == pytest.approx(0.0)
