"""Tests for TradeEngine — atomic buy/sell orchestrator."""

from unittest.mock import patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.positions import InsufficientShares, PositionManager
from scanner.core.trade_engine import TradeEngine
from scanner.core.wallet import InsufficientFunds, WalletService


@pytest.fixture
def setup(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,polymarket_category,updated_at)
            VALUES ('e1','E','Crypto','t');
        INSERT INTO markets (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,updated_at)
            VALUES ('m1','e1','Q','tok_yes','tok_no',0.5,'t');
    """)
    db.conn.commit()
    wallet = WalletService(db)
    wallet.initialize(100.0)
    pm = PositionManager(db)
    engine = TradeEngine(db, wallet, pm)
    return db, wallet, pm, engine


def _mock_price(value: float):
    """Patch _fetch_live_price to return a fixed value."""
    return patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=value,
    )


# --- Buy ----------------------------------------------------------------


def test_execute_buy_yes_happy(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)
    # cost=10, fee = 20 * 0.072 * 0.5 * 0.5 = 0.36
    assert wallet.get_cash() == pytest.approx(100 - 10 - 0.36)
    pos = pm.get_position("m1", "yes")
    assert pos["shares"] == 20.0
    assert pos["avg_cost"] == 0.5
    txs = wallet.list_transactions(limit=5)
    types = [t["type"] for t in txs]
    assert "BUY" in types and "FEE" in types


def test_execute_buy_insufficient_cash_raises_atomic(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5), pytest.raises(InsufficientFunds):
        engine.execute_buy(market_id="m1", side="yes", shares=1000.0)  # cost $500
    # Nothing should have been written.
    assert wallet.get_cash() == 100.0
    assert pm.get_position("m1", "yes") is None
    assert len(wallet.list_transactions()) == 0


# --- Sell ---------------------------------------------------------------


def test_execute_sell_happy(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)
    with _mock_price(0.6):
        engine.execute_sell(market_id="m1", side="yes", shares=10.0)
    # Sold 10 @ 0.6 → proceeds 6; fee = 10 * 0.072 * 0.6 * 0.4 = 0.1728
    # realized = (0.6 - 0.5) * 10 = 1.0
    # cash = 100 - 10 - 0.36 + 6 - 0.1728
    assert wallet.get_cash() == pytest.approx(100 - 10 - 0.36 + 6 - 0.1728)
    pos = pm.get_position("m1", "yes")
    assert pos["shares"] == 10.0
    assert pos["realized_pnl"] == pytest.approx(1.0)


def test_execute_sell_closes_position_when_full(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    with _mock_price(0.7):
        engine.execute_sell(market_id="m1", side="yes", shares=10.0)
    assert pm.get_position("m1", "yes") is None


def test_execute_sell_without_position_raises(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5), pytest.raises(InsufficientShares):
        engine.execute_sell(market_id="m1", side="yes", shares=10.0)
    # No partial state.
    assert wallet.get_cash() == 100.0
    assert len(wallet.list_transactions()) == 0


def test_execute_sell_more_than_held_raises_atomic(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=5.0)
    cash_before = wallet.get_cash()
    tx_count_before = len(wallet.list_transactions())
    with _mock_price(0.6), pytest.raises(InsufficientShares):
        engine.execute_sell(market_id="m1", side="yes", shares=10.0)
    # Post-buy state unchanged; the failed sell wrote nothing.
    assert wallet.get_cash() == cash_before
    assert len(wallet.list_transactions()) == tx_count_before
    assert pm.get_position("m1", "yes")["shares"] == 5.0


# --- Fee semantics ------------------------------------------------------


def test_geopolitics_zero_fee(setup):
    db, wallet, pm, engine = setup
    db.conn.execute(
        "UPDATE events SET polymarket_category='Geopolitics' WHERE event_id='e1'"
    )
    db.conn.commit()
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)
    # cost 10, fee 0 — no FEE row written.
    assert wallet.get_cash() == pytest.approx(90.0)
    types = [t["type"] for t in wallet.list_transactions()]
    assert "FEE" not in types
    assert "BUY" in types


# --- Atomicity: mid-flight failure rollback -----------------------------


def test_execute_buy_midflight_failure_rolls_back(setup):
    """If PositionManager.add_shares fails after wallet debits, everything rolls back."""
    db, wallet, pm, engine = setup

    def boom(**kwargs):
        raise RuntimeError("simulated mid-flight failure")

    with (
        _mock_price(0.5),
        patch.object(pm, "add_shares", side_effect=boom),
        pytest.raises(RuntimeError),
    ):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)

    # Cash must be unchanged; no orphan BUY/FEE rows.
    assert wallet.get_cash() == 100.0
    assert len(wallet.list_transactions()) == 0


def test_execute_sell_midflight_failure_rolls_back(setup):
    """If wallet.credit fails after positions mutate, the position reduction rolls back too."""
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)

    cash_after_buy = wallet.get_cash()
    position_after_buy = pm.get_position("m1", "yes")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated credit failure")

    with (
        _mock_price(0.6),
        patch.object(wallet, "credit", side_effect=boom),
        pytest.raises(RuntimeError),
    ):
        engine.execute_sell(market_id="m1", side="yes", shares=10.0)

    # Position and cash reverted to post-buy state.
    assert wallet.get_cash() == cash_after_buy
    p = pm.get_position("m1", "yes")
    assert p["shares"] == position_after_buy["shares"]
    assert p["realized_pnl"] == 0.0


# --- Return values ------------------------------------------------------


def test_execute_buy_returns_price_cost_fee(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        result = engine.execute_buy(market_id="m1", side="yes", shares=20.0)
    assert result["price"] == 0.5
    assert result["cost"] == pytest.approx(10.0)
    assert result["fee"] == pytest.approx(0.36)


def test_execute_sell_returns_proceeds_fee_realized(setup):
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)
    with _mock_price(0.6):
        result = engine.execute_sell(market_id="m1", side="yes", shares=10.0)
    assert result["price"] == 0.6
    assert result["proceeds"] == pytest.approx(6.0)
    assert result["fee"] == pytest.approx(0.1728)
    assert result["realized_pnl"] == pytest.approx(1.0)


# --- Live price fetch fallback (unit test for the helper) --------------


def test_fetch_live_price_falls_back_to_db_on_http_error(setup):
    db, wallet, pm, engine = setup
    market = dict(db.conn.execute("SELECT * FROM markets WHERE market_id='m1'").fetchone())

    # httpx.get explodes → fallback to market["yes_price"] (seed = 0.5).
    with patch("scanner.core.trade_engine.httpx.get", side_effect=RuntimeError("boom")):
        price = engine._fetch_live_price(market, "yes", buy_side=True)
    assert price == 0.5


def test_fetch_live_price_no_token_returns_db_price(setup):
    db, _, _, engine = setup
    market = {"clob_token_id_yes": None, "yes_price": 0.42}
    assert engine._fetch_live_price(market, "yes", buy_side=True) == 0.42
