"""Tests for WalletService — cash balance + wallet_transactions ledger."""

import pytest

from scanner.core.db import PolilyDB
from scanner.core.wallet import InsufficientFunds, WalletService


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
