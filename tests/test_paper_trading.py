"""Tests for paper trading (SQLite-based)."""

import tempfile

import pytest

from scanner.paper_trading import PaperTradingDB


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    store = PaperTradingDB(db_path)
    yield store
    store.close()


class TestPaperTradeMark:
    def test_mark_trade(self, db: PaperTradingDB):
        trade = db.mark(
            market_id="0xabc",
            title="BTC above 88K?",
            market_type="crypto_threshold",
            side="yes",
            entry_price=0.42,
            beauty_score=82,
            mispricing_signal="moderate",
        )
        assert trade.id is not None
        assert trade.market_id == "0xabc"
        assert trade.side == "yes"
        assert trade.entry_price == 0.42
        assert trade.status == "open"

    def test_mark_generates_unique_ids(self, db: PaperTradingDB):
        t1 = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        t2 = db.mark(market_id="m2", title="M2", side="no", entry_price=0.60)
        assert t1.id != t2.id


class TestPaperTradeQuery:
    def test_list_open(self, db: PaperTradingDB):
        db.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        db.mark(market_id="m2", title="M2", side="yes", entry_price=0.60)
        open_trades = db.list_open()
        assert len(open_trades) == 2

    def test_list_open_excludes_resolved(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        db.resolve(t.id, result="yes")
        assert len(db.list_open()) == 0

    def test_get_by_id(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        fetched = db.get(t.id)
        assert fetched is not None
        assert fetched.market_id == "m1"

    def test_get_nonexistent(self, db: PaperTradingDB):
        assert db.get("nonexistent") is None


class TestPaperTradeResolve:
    def test_resolve_yes_correct(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.40)
        resolved = db.resolve(t.id, result="yes")
        assert resolved.status == "resolved"
        assert resolved.resolved_result == "yes"
        # Bought YES at 0.40, resolved YES -> payout 1.0, profit = 1.0 - 0.40 = 0.60 per share
        # On $20 notional: shares = 20/0.40 = 50, profit = 50 * 0.60 = $30
        assert resolved.paper_pnl is not None
        assert resolved.paper_pnl > 0

    def test_resolve_yes_wrong(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.60)
        resolved = db.resolve(t.id, result="no")
        assert resolved.status == "resolved"
        # Bought YES at 0.60, resolved NO -> payout 0, loss = -0.60 per share
        assert resolved.paper_pnl is not None
        assert resolved.paper_pnl < 0

    def test_resolve_no_correct(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="no", entry_price=0.30)
        resolved = db.resolve(t.id, result="no")
        assert resolved.paper_pnl > 0  # NO bet pays off

    def test_resolve_no_wrong(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="no", entry_price=0.30)
        resolved = db.resolve(t.id, result="yes")
        assert resolved.paper_pnl < 0

    def test_friction_adjusted_pnl(self, db: PaperTradingDB):
        t = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        resolved = db.resolve(t.id, result="yes")
        # friction reduces the PnL
        assert resolved.friction_adjusted_pnl is not None
        assert resolved.friction_adjusted_pnl < resolved.paper_pnl


class TestPaperTradeStats:
    def test_stats_with_resolved_trades(self, db: PaperTradingDB):
        t1 = db.mark(market_id="m1", title="M1", side="yes", entry_price=0.40)
        t2 = db.mark(market_id="m2", title="M2", side="yes", entry_price=0.60)
        t3 = db.mark(market_id="m3", title="M3", side="yes", entry_price=0.50)
        db.resolve(t1.id, result="yes")  # win
        db.resolve(t2.id, result="no")   # loss
        db.resolve(t3.id, result="yes")  # win

        stats = db.stats()
        assert stats["total_trades"] == 3
        assert stats["resolved"] == 3
        assert stats["wins"] == 2
        assert stats["losses"] == 1
        assert abs(stats["win_rate"] - 2 / 3) < 0.01
        assert stats["total_paper_pnl"] != 0

    def test_stats_empty(self, db: PaperTradingDB):
        stats = db.stats()
        assert stats["total_trades"] == 0
        assert stats["win_rate"] == 0.0

    def test_stats_with_open_trades(self, db: PaperTradingDB):
        db.mark(market_id="m1", title="M1", side="yes", entry_price=0.50)
        stats = db.stats()
        assert stats["total_trades"] == 1
        assert stats["resolved"] == 0
        assert stats["open"] == 1
