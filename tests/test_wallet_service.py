"""Tests for WalletService — cash balance + wallet_transactions ledger."""

import pytest

from polily.core.db import PolilyDB
from polily.core.wallet import InsufficientFunds, WalletService


@pytest.fixture
def wallet(tmp_path):
    db = PolilyDB(tmp_path / "test.db")
    svc = WalletService(db)
    svc.initialize(starting_balance=100.0)
    return svc


def test_initialize_creates_singleton(wallet):
    assert wallet.get_cash() == 100.0
    assert wallet.get_starting_balance() == 100.0


def test_initialize_is_idempotent(wallet):
    wallet.initialize(starting_balance=999.0)  # second call
    assert wallet.get_cash() == 100.0  # unchanged


def test_topup_increases_cash_and_records_tx(wallet):
    wallet.topup(50.0)
    assert wallet.get_cash() == 150.0
    txs = wallet.list_transactions(limit=1)
    assert txs[0]["type"] == "TOPUP"
    assert txs[0]["amount_usd"] == 50.0
    assert txs[0]["balance_after"] == 150.0


def test_withdraw_decreases_cash(wallet):
    wallet.withdraw(30.0)
    assert wallet.get_cash() == 70.0


def test_withdraw_over_cash_raises(wallet):
    with pytest.raises(InsufficientFunds):
        wallet.withdraw(200.0)


def test_cumulative_realized_pnl_empty(wallet):
    """Fresh wallet has 0 cumulative realized P&L."""
    assert wallet.get_cumulative_realized_pnl() == 0.0
    assert wallet.get_snapshot()["cumulative_realized_pnl"] == 0.0


def test_cumulative_realized_pnl_sums_sell_and_resolve(wallet):
    """SUM(realized_pnl) over SELL + RESOLVE tx types."""
    # A winning SELL
    wallet.credit(
        3.0,
        tx_type="SELL",
        market_id="m1", event_id="e1", side="yes",
        shares=5.0, price=0.6,
        realized_pnl=0.5,  # (0.6 - 0.5) × 5
    )
    # A losing RESOLVE (losing side gets $0 credit but negative realized_pnl)
    wallet.credit(
        0.0,
        tx_type="RESOLVE",
        market_id="m2", event_id="e2", side="no",
        shares=10.0, price=0.0,
        realized_pnl=-4.0,  # -avg_cost × shares
    )
    # A winning RESOLVE
    wallet.credit(
        10.0,
        tx_type="RESOLVE",
        market_id="m3", event_id="e3", side="yes",
        shares=10.0, price=1.0,
        realized_pnl=5.5,  # (1.0 - 0.45) × 10
    )

    assert wallet.get_cumulative_realized_pnl() == pytest.approx(0.5 + (-4.0) + 5.5)
    assert wallet.get_snapshot()["cumulative_realized_pnl"] == pytest.approx(2.0)


def test_cumulative_realized_pnl_ignores_non_realizing_types(wallet):
    """TOPUP / WITHDRAW / BUY / FEE / MIGRATION do not contribute."""
    wallet.topup(20.0)
    wallet.withdraw(5.0)
    wallet.deduct(
        1.0, tx_type="FEE",
        market_id="m1", event_id="e1", side="yes",
    )
    wallet.deduct(
        10.0, tx_type="BUY",
        market_id="m1", event_id="e1", side="yes",
        shares=20.0, price=0.5,
    )
    # Also a real SELL so we know the sum isn't always 0.
    wallet.credit(
        6.0, tx_type="SELL",
        market_id="m1", event_id="e1", side="yes",
        shares=10.0, price=0.6,
        realized_pnl=1.0,
    )
    assert wallet.get_cumulative_realized_pnl() == pytest.approx(1.0)


def test_deduct_for_trade_records_type(wallet):
    wallet.deduct(
        10.0,
        tx_type="BUY",
        market_id="m1",
        event_id="e1",
        side="yes",
        shares=20.0,
        price=0.5,
    )
    assert wallet.get_cash() == 90.0
    txs = wallet.list_transactions(limit=1)
    assert txs[0]["type"] == "BUY"
    assert txs[0]["amount_usd"] == -10.0
    assert txs[0]["market_id"] == "m1"


def test_deduct_insufficient_raises_does_not_alter_cash(wallet):
    with pytest.raises(InsufficientFunds):
        wallet.deduct(500.0, tx_type="BUY")
    assert wallet.get_cash() == 100.0  # unchanged
    # No orphan ledger row either.
    assert wallet.list_transactions() == []


def test_credit_from_resolve(wallet):
    wallet.credit(
        25.0, tx_type="RESOLVE", market_id="m1", realized_pnl=5.0, notes="YES won"
    )
    assert wallet.get_cash() == 125.0
    txs = wallet.list_transactions(limit=1)
    assert txs[0]["realized_pnl"] == 5.0


def test_get_equity_sums_cash_and_positions(wallet):
    # No positions yet → equity = cash
    assert wallet.get_equity(positions_market_value=0.0) == 100.0
    assert wallet.get_equity(positions_market_value=25.3) == 125.3


def test_topup_total_and_withdraw_total_accumulate(wallet):
    wallet.topup(50.0)
    wallet.topup(30.0)
    wallet.withdraw(20.0)
    snap = wallet.get_snapshot()
    assert snap["topup_total"] == 80.0
    assert snap["withdraw_total"] == 20.0


# --- Atomicity contract (required by Task 1.6 TradeEngine) ---------------


def test_topup_respects_commit_false(tmp_path):
    """commit=False leaves the change in an open transaction, visible on same conn but uncommitted."""
    db = PolilyDB(tmp_path / "t.db")
    svc = WalletService(db)
    svc.initialize(starting_balance=100.0)
    svc.topup(10.0, commit=False)
    # Same connection sees the pending change.
    assert svc.get_cash() == 110.0
    # Rolling back should revert everything.
    db.conn.rollback()
    assert svc.get_cash() == 100.0
    assert svc.list_transactions() == []


def test_deduct_respects_commit_false(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    svc = WalletService(db)
    svc.initialize(starting_balance=100.0)
    svc.deduct(20.0, tx_type="BUY", commit=False, market_id="m1", side="yes")
    assert svc.get_cash() == 80.0
    db.conn.rollback()
    assert svc.get_cash() == 100.0


def test_list_transactions_filter_by_type(wallet):
    wallet.topup(10.0)
    wallet.topup(20.0)
    wallet.withdraw(5.0)
    topups = wallet.list_transactions(tx_type="TOPUP")
    assert len(topups) == 2
    assert all(t["type"] == "TOPUP" for t in topups)


# --- Input validation: boundaries (TUI/CLI callers) ---------------------


def test_topup_rejects_non_positive(wallet):
    with pytest.raises(ValueError, match="positive"):
        wallet.topup(0)
    with pytest.raises(ValueError, match="positive"):
        wallet.topup(-50.0)


def test_withdraw_rejects_non_positive(wallet):
    with pytest.raises(ValueError, match="positive"):
        wallet.withdraw(-1.0)


def test_deduct_rejects_bad_tx_type(wallet):
    with pytest.raises(ValueError, match="tx_type"):
        wallet.deduct(10.0, tx_type="HACK")
    # Also rejects SELL/RESOLVE (those belong to credit).
    with pytest.raises(ValueError, match="tx_type"):
        wallet.deduct(10.0, tx_type="SELL")
    assert wallet.get_cash() == 100.0


def test_credit_rejects_bad_tx_type(wallet):
    with pytest.raises(ValueError, match="tx_type"):
        wallet.credit(10.0, tx_type="BUY")
    assert wallet.get_cash() == 100.0


def test_credit_allows_zero_amount(wallet):
    """Zero-value RESOLVE (losing side of market) is legal."""
    wallet.credit(0.0, tx_type="RESOLVE", market_id="m1", realized_pnl=-5.0)
    assert wallet.get_cash() == 100.0
    tx = wallet.list_transactions(limit=1)[0]
    assert tx["type"] == "RESOLVE"
    assert tx["amount_usd"] == 0.0
    assert tx["realized_pnl"] == -5.0


# --- Atomicity happy-path (TradeEngine contract dependency) -------------


def test_multiple_commit_false_ops_commit_together(tmp_path):
    """Multiple commit=False writes must persist together on a single commit call."""
    db = PolilyDB(tmp_path / "t.db")
    svc = WalletService(db)
    svc.initialize(starting_balance=100.0)
    # TradeEngine-style: debit cost + debit fee, then one commit.
    svc.deduct(10.0, tx_type="BUY", commit=False, market_id="m1", side="yes")
    svc.deduct(0.36, tx_type="FEE", commit=False, market_id="m1", side="yes")
    # Both visible on same connection before commit.
    assert svc.get_cash() == pytest.approx(89.64)
    db.conn.commit()
    # After commit, state is durable — verify via fresh connection.
    db2 = PolilyDB(tmp_path / "t.db")
    assert db2.conn.execute("SELECT cash_usd FROM wallet WHERE id=1").fetchone()[
        "cash_usd"
    ] == pytest.approx(89.64)
    assert (
        db2.conn.execute("SELECT COUNT(*) FROM wallet_transactions").fetchone()[0] == 2
    )
