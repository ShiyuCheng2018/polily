"""Tests for paper trading graduation assessment."""

import pytest

from scanner.graduation import assess_graduation
from scanner.paper_trading import PaperTradingDB


@pytest.fixture
def db(polily_db):
    return PaperTradingDB(polily_db)


class TestGraduation:
    def test_not_ready_too_few_trades(self, db):
        for i in range(5):
            t = db.mark(market_id=f"m{i}", title=f"M{i}", side="yes", entry_price=0.50)
            db.resolve(t.id, result="yes")
        result = assess_graduation(db)
        assert result.ready is False
        assert "trades" in result.reason.lower() or "10" in result.reason

    def test_ready_when_all_pass(self, db):
        # 12 trades, 8 wins, 4 losses, positive friction-adjusted PnL
        for i in range(8):
            t = db.mark(market_id=f"w{i}", title=f"Win{i}", side="yes", entry_price=0.40)
            db.resolve(t.id, result="yes")
        for i in range(4):
            t = db.mark(market_id=f"l{i}", title=f"Loss{i}", side="yes", entry_price=0.60)
            db.resolve(t.id, result="no")
        result = assess_graduation(db)
        assert result.ready is True

    def test_not_ready_negative_pnl(self, db):
        # 10 trades, 3 wins 7 losses → negative PnL
        for i in range(3):
            t = db.mark(market_id=f"w{i}", title=f"W{i}", side="yes", entry_price=0.40)
            db.resolve(t.id, result="yes")
        for i in range(7):
            t = db.mark(market_id=f"l{i}", title=f"L{i}", side="yes", entry_price=0.60)
            db.resolve(t.id, result="no")
        result = assess_graduation(db)
        assert result.ready is False

    def test_result_has_all_checks(self, db):
        for i in range(10):
            t = db.mark(market_id=f"m{i}", title=f"M{i}", side="yes", entry_price=0.50)
            db.resolve(t.id, result="yes" if i < 6 else "no")
        result = assess_graduation(db)
        assert len(result.checks) >= 4

    def test_empty_db(self, db):
        result = assess_graduation(db)
        assert result.ready is False
