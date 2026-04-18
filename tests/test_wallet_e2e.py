"""End-to-end lifecycle tests for the v0.6.0 wallet system.

Phase 1 integration: exercises the DB → WalletService → PositionManager →
TradeEngine → wallet_reset stack in realistic user flows. Live-price fetch
is the only thing mocked.
"""

from unittest.mock import patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.positions import PositionManager
from scanner.core.trade_engine import TradeEngine
from scanner.core.wallet import WalletService
from scanner.core.wallet_reset import reset_wallet


def _seed_crypto_market(db: PolilyDB) -> None:
    """Crypto short-term market (crypto_fees_v2, rate 0.072) — fees_enabled."""
    db.conn.executescript("""
        INSERT INTO events (event_id,title,polymarket_category,updated_at)
            VALUES ('e1','BTC above 100k end of week?','Crypto','t');
        INSERT INTO markets
            (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,fees_enabled,fee_rate,updated_at)
            VALUES ('m1','e1','BTC > 100k','tok_yes','tok_no',0.5,1,0.072,'t');
    """)
    db.conn.commit()


def _services(db: PolilyDB) -> tuple[WalletService, PositionManager, TradeEngine]:
    wallet = WalletService(db)
    pm = PositionManager(db)
    engine = TradeEngine(db, wallet, pm)
    return wallet, pm, engine


def _mock_price(value: float):
    return patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=value,
    )


def test_full_wallet_lifecycle(tmp_path):
    """Topup → buy → partial sell → reset.

    Verifies each arithmetic step against the documented Polymarket Crypto
    fee formula (rate=0.072, quadratic in price around 0.5) and the
    weighted-average cost basis contract.
    """
    db = PolilyDB(tmp_path / "t.db")
    _seed_crypto_market(db)
    wallet, pm, engine = _services(db)

    # --- Topup ----------------------------------------------------------
    wallet.topup(50.0)
    assert wallet.get_cash() == 150.0
    assert wallet.get_snapshot()["topup_total"] == 50.0

    # --- Buy 20 YES @ 0.5 ----------------------------------------------
    # cost = 20*0.5 = 10; fee = 20*0.072*0.5*0.5 = 0.36
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)
    assert wallet.get_cash() == pytest.approx(150 - 10 - 0.36)
    pos = pm.get_position("m1", "yes")
    assert pos["shares"] == 20.0
    assert pos["avg_cost"] == 0.5
    assert pos["cost_basis"] == pytest.approx(10.0)

    # --- Partial sell 10 YES @ 0.6 -------------------------------------
    # proceeds = 10*0.6 = 6; fee = 10*0.072*0.6*0.4 = 0.1728
    # realized = (0.6-0.5)*10 = 1.0
    with _mock_price(0.6):
        result = engine.execute_sell(market_id="m1", side="yes", shares=10.0)
    assert result["realized_pnl"] == pytest.approx(1.0)
    assert wallet.get_cash() == pytest.approx(150 - 10 - 0.36 + 6 - 0.1728)
    pos = pm.get_position("m1", "yes")
    assert pos["shares"] == 10.0
    assert pos["avg_cost"] == 0.5  # unchanged on reduce
    assert pos["realized_pnl"] == pytest.approx(1.0)

    # Ledger sanity: TOPUP + BUY + FEE + SELL + FEE = 5 rows
    txs = wallet.list_transactions()
    types = sorted(t["type"] for t in txs)
    assert types == ["BUY", "FEE", "FEE", "SELL", "TOPUP"]

    # --- Reset ----------------------------------------------------------
    reset_wallet(db, starting_balance=100.0)
    assert wallet.get_cash() == 100.0
    assert pm.get_position("m1", "yes") is None
    assert wallet.list_transactions() == []
    # Event / market preserved.
    assert db.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert db.conn.execute("SELECT COUNT(*) FROM markets").fetchone()[0] == 1


def test_add_to_existing_position_weighted_avg_e2e(tmp_path):
    """Two buys at different prices produce a correctly weighted-averaged position."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_crypto_market(db)
    wallet, pm, engine = _services(db)

    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.7):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    pos = pm.get_position("m1", "yes")
    assert pos["shares"] == 20.0
    assert pos["avg_cost"] == pytest.approx(0.6)
    assert pos["cost_basis"] == pytest.approx(12.0)


def test_yes_and_no_positions_coexist_e2e(tmp_path):
    """Buying both sides of the same market creates two independent positions."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_crypto_market(db)
    wallet, pm, engine = _services(db)

    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="no", shares=5.0)

    yes_pos = pm.get_position("m1", "yes")
    no_pos = pm.get_position("m1", "no")
    assert yes_pos["shares"] == 10.0
    assert no_pos["shares"] == 5.0


def test_full_exit_deletes_position_e2e(tmp_path):
    """Selling all shares closes the position entirely."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_crypto_market(db)
    wallet, pm, engine = _services(db)

    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.7):
        engine.execute_sell(market_id="m1", side="yes", shares=10.0)

    assert pm.get_position("m1", "yes") is None
    # Realized P&L captured in the SELL ledger row.
    sell_tx = wallet.list_transactions(tx_type="SELL")[0]
    assert sell_tx["realized_pnl"] == pytest.approx(2.0)  # (0.7-0.5)*10


def test_insufficient_cash_rollback_preserves_all_state_e2e(tmp_path):
    """A failed buy leaves NO traces: cash, positions, ledger all unchanged."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_crypto_market(db)
    wallet, pm, engine = _services(db)

    # Establish a known good state first.
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    good_cash = wallet.get_cash()
    good_tx_count = len(wallet.list_transactions())
    good_shares = pm.get_position("m1", "yes")["shares"]

    # Attempt a trade that exceeds available cash.
    from scanner.core.wallet import InsufficientFunds
    with _mock_price(0.9), pytest.raises(InsufficientFunds):
        engine.execute_buy(market_id="m1", side="yes", shares=10000.0)

    # All three state surfaces unchanged.
    assert wallet.get_cash() == good_cash
    assert len(wallet.list_transactions()) == good_tx_count
    assert pm.get_position("m1", "yes")["shares"] == good_shares


def test_geopolitics_zero_fee_e2e(tmp_path):
    """Non-Crypto category (Geopolitics, fee=0) writes no FEE row, cash reflects
    bare cost/proceeds."""
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,polymarket_category,updated_at)
            VALUES ('e1','Trump wins 2028','Geopolitics','t');
        INSERT INTO markets
            (market_id,event_id,question,clob_token_id_yes,yes_price,updated_at)
            VALUES ('m1','e1','Q','tok','0.4','t');
    """)
    db.conn.commit()
    wallet, pm, engine = _services(db)

    with _mock_price(0.4):
        engine.execute_buy(market_id="m1", side="yes", shares=25.0)
    # cost = 25*0.4 = 10; fee = 0 (Geopolitics)
    assert wallet.get_cash() == pytest.approx(90.0)
    assert [t["type"] for t in wallet.list_transactions()] == ["BUY"]


def test_polilydb_reopen_preserves_full_lifecycle_e2e(tmp_path):
    """State persists across PolilyDB connections — the wallet survives a restart."""
    db = PolilyDB(tmp_path / "t.db")
    _seed_crypto_market(db)
    wallet, pm, engine = _services(db)

    wallet.topup(50.0)
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    cash_before = wallet.get_cash()
    db.close()

    # Reopen — auto-migration runs but is a no-op (bookmark exists or wallet present).
    db2 = PolilyDB(tmp_path / "t.db")
    wallet2 = WalletService(db2)
    pm2 = PositionManager(db2)
    assert wallet2.get_cash() == cash_before
    assert pm2.get_position("m1", "yes")["shares"] == 10.0
    assert wallet2.get_snapshot()["topup_total"] == 50.0
