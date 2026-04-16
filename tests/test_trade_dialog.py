"""Tests for paper trade creation from trade dialog."""

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.paper_store import create_paper_trade, get_event_open_trades


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _seed(db, event_id="ev1", market_id="m1", yes_price=0.55):
    upsert_event(EventRow(event_id=event_id, title="BTC April", updated_at="now"), db)
    upsert_market(MarketRow(
        market_id=market_id, event_id=event_id,
        question="Will BTC reach $80K?",
        yes_price=yes_price, no_price=round(1 - yes_price, 4),
        updated_at="now",
    ), db)


class TestPaperTradeCreation:
    def test_create_yes_trade(self, db):
        _seed(db, yes_price=0.25)
        create_paper_trade(
            event_id="ev1", market_id="m1",
            title="Will BTC reach $80K?",
            side="yes", entry_price=0.25,
            position_size_usd=10.0,
            db=db,
        )
        trades = get_event_open_trades("ev1", db)
        assert len(trades) == 1
        assert trades[0]["side"] == "yes"
        assert trades[0]["entry_price"] == 0.25
        assert trades[0]["position_size_usd"] == 10.0

    def test_create_no_trade(self, db):
        _seed(db, yes_price=0.25)
        create_paper_trade(
            event_id="ev1", market_id="m1",
            title="Will BTC reach $80K?",
            side="no", entry_price=0.75,
            position_size_usd=20.0,
            db=db,
        )
        trades = get_event_open_trades("ev1", db)
        assert len(trades) == 1
        assert trades[0]["side"] == "no"
        assert trades[0]["entry_price"] == 0.75

    def test_multiple_trades_same_event(self, db):
        _seed(db)
        upsert_market(MarketRow(
            market_id="m2", event_id="ev1",
            question="Will BTC reach $85K?",
            yes_price=0.10, no_price=0.90,
            updated_at="now",
        ), db)
        create_paper_trade(
            event_id="ev1", market_id="m1", title="$80K",
            side="yes", entry_price=0.55, position_size_usd=10.0, db=db,
        )
        create_paper_trade(
            event_id="ev1", market_id="m2", title="$85K",
            side="no", entry_price=0.90, position_size_usd=15.0, db=db,
        )
        trades = get_event_open_trades("ev1", db)
        assert len(trades) == 2
