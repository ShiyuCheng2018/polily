"""Tests for the intelligence layer — signal computation for monitored events."""
import json

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import (
    EventRow,
    MarketRow,
    update_market_prices,
    upsert_event,
    upsert_market,
)
from scanner.core.monitor_store import upsert_event_monitor
from scanner.daemon.poll_job import _run_intelligence_layer
from scanner.monitor.store import get_event_movements


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed_monitored_event(db, event_id="ev1", market_ids=("m1",), neg_risk=False):
    """Create an event with markets, enable monitoring, set prices."""
    upsert_event(
        EventRow(
            event_id=event_id,
            title="E",
            neg_risk=neg_risk,
            market_count=len(market_ids),
            updated_at="now",
        ),
        db,
    )
    for mid in market_ids:
        upsert_market(
            MarketRow(
                market_id=mid,
                event_id=event_id,
                question=f"Q {mid}",
                clob_token_id_yes=f"tok_{mid}",
                updated_at="now",
            ),
            db,
        )
        update_market_prices(
            mid,
            yes_price=0.55,
            no_price=0.45,
            best_bid=0.54,
            best_ask=0.56,
            spread=0.02,
            bid_depth=500.0,
            ask_depth=300.0,
            book_bids=json.dumps([{"price": 0.54, "size": 500}]),
            book_asks=json.dumps([{"price": 0.56, "size": 300}]),
            recent_trades=json.dumps(
                [{"price": 0.55, "size": 100, "side": "BUY"}]
            ),
            db=db,
        )
    upsert_event_monitor(event_id, auto_monitor=True, db=db)


class TestIntelligenceLayer:
    def test_computes_signals_for_monitored_event(self, db):
        _seed_monitored_event(db)
        _run_intelligence_layer(db)
        entries = get_event_movements("ev1", db, hours=1)
        assert len(entries) >= 1
        assert entries[0]["event_id"] == "ev1"
        assert entries[0]["market_id"] == "m1"  # sub-market level entry
        # Cold start (< 5 entries): magnitude and quality forced to 0, label=noise
        assert entries[0]["magnitude"] == 0
        assert entries[0]["quality"] == 0
        assert entries[0]["label"] == "noise"

    def test_skips_non_monitored_events(self, db):
        """Events without auto_monitor should not get signal computation."""
        upsert_event(
            EventRow(event_id="ev1", title="E", updated_at="now"), db
        )
        upsert_market(
            MarketRow(
                market_id="m1",
                event_id="ev1",
                question="Q",
                clob_token_id_yes="tok1",
                updated_at="now",
            ),
            db,
        )
        update_market_prices(
            "m1", yes_price=0.55, bid_depth=500, ask_depth=300, db=db
        )
        # NOT monitored → no upsert_event_monitor
        _run_intelligence_layer(db)
        entries = get_event_movements("ev1", db, hours=1)
        assert len(entries) == 0

    def test_neg_risk_event_gets_event_level_metrics(self, db):
        """negRisk events should get an additional event-level movement_log entry."""
        _seed_monitored_event(
            db,
            event_id="ev1",
            market_ids=("m1", "m2", "m3"),
            neg_risk=True,
        )
        # Set different prices for each sub-market
        update_market_prices("m1", yes_price=0.5, db=db)
        update_market_prices("m2", yes_price=0.3, db=db)
        update_market_prices("m3", yes_price=0.2, db=db)

        _run_intelligence_layer(db)

        entries = get_event_movements("ev1", db, hours=1)
        # Should have 3 sub-market entries + 1 event-level entry
        sub_entries = [e for e in entries if e["market_id"] is not None]
        event_entries = [e for e in entries if e["market_id"] is None]
        assert len(sub_entries) == 3
        assert len(event_entries) == 1

        # Event-level entry should have metrics in snapshot
        snapshot = json.loads(event_entries[0]["snapshot"])
        assert "overround" in snapshot
        assert "entropy" in snapshot
        assert "leader_id" in snapshot

    def test_binary_event_no_event_level_metrics(self, db):
        """Binary events (single market, not negRisk) should NOT get event-level metrics."""
        _seed_monitored_event(
            db, event_id="ev1", market_ids=("m1",), neg_risk=False
        )
        _run_intelligence_layer(db)
        entries = get_event_movements("ev1", db, hours=1)
        event_entries = [e for e in entries if e["market_id"] is None]
        assert len(event_entries) == 0  # no event-level entry for binary
