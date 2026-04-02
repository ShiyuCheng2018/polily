"""Tests for paper trading (SQLite-backed via PolilyDB)."""

import pytest

from scanner.paper_trading import PaperTradingDB


@pytest.fixture
def ptdb(polily_db):
    return PaperTradingDB(polily_db)


class TestPaperTradeMark:
    def test_mark_trade(self, ptdb: PaperTradingDB):
        trade = ptdb.mark(
            market_id="0xabc",
            title="BTC above 88K?",
            market_type="crypto_threshold",
            side="yes",
            entry_price=0.42,
            structure_score=82,
            mispricing_signal="moderate",
        )
        assert trade.id is not None
        assert trade.market_id == "0xabc"
        assert trade.side == "yes"
        assert trade.entry_price == 0.42
        assert trade.structure_score == 82
        assert trade.status == "open"

    def test_mark_generates_unique_ids(self, ptdb: PaperTradingDB):
        t1 = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        t2 = ptdb.mark(market_id="m2", title="M2", side="no", entry_price=0.60)
        assert t1.id != t2.id


class TestPaperTradeQuery:
    def test_list_open(self, ptdb: PaperTradingDB):
        ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        ptdb.mark(market_id="m2", title="M2", side="yes", entry_price=0.60)
        assert len(ptdb.list_open()) == 2

    def test_list_open_excludes_resolved(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        ptdb.resolve(t.id, result="yes")
        assert len(ptdb.list_open()) == 0

    def test_get_by_id(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        fetched = ptdb.get(t.id)
        assert fetched is not None
        assert fetched.market_id == "m1"

    def test_get_nonexistent(self, ptdb: PaperTradingDB):
        assert ptdb.get("nonexistent") is None


class TestPaperTradeResolve:
    def test_resolve_yes_correct(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.40)
        resolved = ptdb.resolve(t.id, result="yes")
        assert resolved.status == "resolved"
        assert resolved.resolved_result == "yes"
        assert resolved.paper_pnl is not None
        assert resolved.paper_pnl > 0

    def test_resolve_yes_wrong(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.60)
        resolved = ptdb.resolve(t.id, result="no")
        assert resolved.paper_pnl < 0

    def test_resolve_no_correct(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="no", entry_price=0.30)
        resolved = ptdb.resolve(t.id, result="no")
        assert resolved.paper_pnl > 0

    def test_resolve_no_wrong(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="no", entry_price=0.30)
        resolved = ptdb.resolve(t.id, result="yes")
        assert resolved.paper_pnl < 0

    def test_friction_adjusted_pnl(self, ptdb: PaperTradingDB):
        t = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        resolved = ptdb.resolve(t.id, result="yes")
        assert resolved.friction_adjusted_pnl is not None
        assert resolved.friction_adjusted_pnl < resolved.paper_pnl


class TestPaperTradeStats:
    def test_stats_with_resolved_trades(self, ptdb: PaperTradingDB):
        t1 = ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.40)
        t2 = ptdb.mark(market_id="m2", title="M2", side="yes", entry_price=0.60)
        t3 = ptdb.mark(market_id="m3", title="M3", side="yes", entry_price=0.50)
        ptdb.resolve(t1.id, result="yes")
        ptdb.resolve(t2.id, result="no")
        ptdb.resolve(t3.id, result="yes")
        stats = ptdb.stats()
        assert stats["total_trades"] == 3
        assert stats["resolved"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert abs(stats["win_rate"] - 2 / 3) < 0.01

    def test_stats_empty(self, ptdb: PaperTradingDB):
        stats = ptdb.stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0

    def test_stats_with_open_trades(self, ptdb: PaperTradingDB):
        ptdb.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        stats = ptdb.stats()
        assert stats["total_trades"] == 1
        assert stats["open"] == 1
        assert stats["resolved"] == 0
