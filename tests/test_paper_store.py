"""Tests for paper trade store."""
import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.paper_store import (
    create_paper_trade,
    get_event_open_trades,
    get_open_trades,
    get_resolved_trades,
    get_trade_stats,
    resolve_trade,
)


@pytest.fixture
def db(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    yield db
    db.close()


def _setup(db, event_id="ev1", market_id="m1"):
    upsert_event(EventRow(event_id=event_id, title="E", updated_at="now"), db)
    upsert_market(MarketRow(market_id=market_id, event_id=event_id, question="Q", updated_at="now"), db)


class TestCreateAndGet:
    def test_create_paper_trade(self, db):
        _setup(db)
        trade_id = create_paper_trade(
            event_id="ev1", market_id="m1", title="BTC above 88k?",
            side="yes", entry_price=0.55, position_size_usd=20.0, db=db,
        )
        assert trade_id is not None
        assert len(trade_id) > 0

    def test_get_open_trades(self, db):
        _setup(db, "ev1", "m1")
        _setup(db, "ev2", "m2")
        create_paper_trade(event_id="ev1", market_id="m1", title="T1",
                          side="yes", entry_price=0.5, position_size_usd=20, db=db)
        create_paper_trade(event_id="ev2", market_id="m2", title="T2",
                          side="no", entry_price=0.3, position_size_usd=15, db=db)
        trades = get_open_trades(db)
        assert len(trades) == 2
        sides = {t["side"] for t in trades}
        assert sides == {"yes", "no"}

    def test_get_event_open_trades(self, db):
        _setup(db, "ev1", "m1")
        _setup(db, "ev2", "m2")
        create_paper_trade(event_id="ev1", market_id="m1", title="T1",
                          side="yes", entry_price=0.5, position_size_usd=20, db=db)
        create_paper_trade(event_id="ev2", market_id="m2", title="T2",
                          side="no", entry_price=0.3, position_size_usd=15, db=db)
        ev1_trades = get_event_open_trades("ev1", db)
        assert len(ev1_trades) == 1
        assert ev1_trades[0]["event_id"] == "ev1"


class TestResolve:
    def test_resolve_trade_yes(self, db):
        _setup(db)
        tid = create_paper_trade(event_id="ev1", market_id="m1", title="T",
                                side="yes", entry_price=0.5, position_size_usd=20, db=db)
        resolve_trade(tid, result="yes", db=db)
        assert len(get_open_trades(db)) == 0
        resolved = get_resolved_trades(db)
        assert len(resolved) == 1
        assert resolved[0]["resolved_result"] == "yes"
        assert resolved[0]["paper_pnl"] is not None

    def test_resolve_trade_no_side(self, db):
        _setup(db)
        tid = create_paper_trade(event_id="ev1", market_id="m1", title="T",
                                side="no", entry_price=0.3, position_size_usd=20, db=db)
        resolve_trade(tid, result="no", db=db)
        resolved = get_resolved_trades(db)
        assert len(resolved) == 1
        assert resolved[0]["paper_pnl"] is not None


class TestStats:
    def test_trade_stats(self, db):
        _setup(db)
        create_paper_trade(event_id="ev1", market_id="m1", title="T1",
                          side="yes", entry_price=0.5, position_size_usd=20, db=db)
        tid2 = create_paper_trade(event_id="ev1", market_id="m1", title="T2",
                                 side="no", entry_price=0.4, position_size_usd=15, db=db)
        resolve_trade(tid2, result="no", db=db)
        stats = get_trade_stats(db)
        assert stats["open"] == 1
        assert stats["resolved"] == 1
        assert stats["total"] == 2

    def test_empty_stats(self, db):
        stats = get_trade_stats(db)
        assert stats["open"] == 0
        assert stats["resolved"] == 0
        assert stats["total"] == 0
