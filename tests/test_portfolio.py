"""Tests for portfolio service helpers."""

import pytest

from scanner.core.db import PolilyDB
from scanner.paper_trading import PaperTradingDB


@pytest.fixture
def db(tmp_path):
    _db = PolilyDB(tmp_path / "test.db")
    yield _db
    _db.close()


def test_list_resolved_returns_only_resolved(db):
    ptdb = PaperTradingDB(db)
    # Create open trade
    ptdb.mark("m1", "Market 1", "yes", 0.50)
    # Create and resolve another
    t2 = ptdb.mark("m2", "Market 2", "no", 0.40)
    ptdb.resolve(t2.id, "yes")  # NO side, result=yes → loss

    resolved = ptdb.list_resolved()
    assert len(resolved) == 1
    assert resolved[0].market_id == "m2"
    assert resolved[0].status == "resolved"


def test_list_resolved_empty(db):
    ptdb = PaperTradingDB(db)
    assert ptdb.list_resolved() == []


def test_resolved_trade_has_pnl(db):
    ptdb = PaperTradingDB(db)
    t = ptdb.mark("m1", "Market 1", "yes", 0.50)
    ptdb.resolve(t.id, "yes")  # YES side, result=yes → win

    resolved = ptdb.list_resolved()
    assert len(resolved) == 1
    assert resolved[0].paper_pnl is not None
    assert resolved[0].paper_pnl > 0  # won


def test_settlement_price_yes_wins(db):
    """side=yes, result=yes → win (pnl > 0)."""
    ptdb = PaperTradingDB(db)
    t = ptdb.mark("m1", "Test", "yes", 0.60)
    ptdb.resolve(t.id, "yes")
    resolved = ptdb.list_resolved()
    assert resolved[0].paper_pnl > 0


def test_settlement_price_yes_loses(db):
    """side=yes, result=no → loss (pnl < 0)."""
    ptdb = PaperTradingDB(db)
    t = ptdb.mark("m1", "Test", "yes", 0.60)
    ptdb.resolve(t.id, "no")
    resolved = ptdb.list_resolved()
    assert resolved[0].paper_pnl < 0


def test_settlement_price_no_wins(db):
    """side=no, result=no → win (pnl > 0)."""
    ptdb = PaperTradingDB(db)
    t = ptdb.mark("m1", "Test", "no", 0.40)
    ptdb.resolve(t.id, "no")
    resolved = ptdb.list_resolved()
    assert resolved[0].paper_pnl > 0


def test_settlement_price_no_loses(db):
    """side=no, result=yes → loss (pnl < 0)."""
    ptdb = PaperTradingDB(db)
    t = ptdb.mark("m1", "Test", "no", 0.40)
    ptdb.resolve(t.id, "yes")
    resolved = ptdb.list_resolved()
    assert resolved[0].paper_pnl < 0
