"""Tests for TradeEngine — atomic buy/sell orchestrator."""

from unittest.mock import patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.positions import InsufficientShares, PositionManager
from scanner.core.trade_engine import TradeEngine
from scanner.core.wallet import InsufficientFunds, WalletService


@pytest.fixture
def setup(tmp_path):
    """Seeded market has fees enabled (crypto_fees_v2 rate 0.072) so the
    engine's fee arithmetic is exercised. Tests that want a fee-free market
    can override via the `fees_off_setup` fixture below.
    """
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,updated_at)
            VALUES ('e1','E','t');
        INSERT INTO markets (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,fees_enabled,fee_rate,updated_at)
            VALUES ('m1','e1','Q','tok_yes','tok_no',0.5,1,0.072,'t');
    """)
    db.conn.commit()
    wallet = WalletService(db)
    wallet.initialize(100.0)
    pm = PositionManager(db)
    engine = TradeEngine(db, wallet, pm)
    return db, wallet, pm, engine


@pytest.fixture
def fees_off_setup(tmp_path):
    """Variant where the seeded market has fees disabled — matches the common
    Polymarket case (Politics / Sports majors / Geopolitics)."""
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript("""
        INSERT INTO events (event_id,title,updated_at)
            VALUES ('e1','E-fees-off','t');
        INSERT INTO markets (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,fees_enabled,fee_rate,updated_at)
            VALUES ('m1','e1','Q','tok_yes','tok_no',0.5,0,NULL,'t');
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


def test_market_with_fees_disabled_charges_zero_fee(fees_off_setup):
    """Polymarket's common case: market.feesEnabled=false → no fee row."""
    db, wallet, pm, engine = fees_off_setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=20.0)
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


# --- Guardrails (review-surfaced) --------------------------------------


def test_execute_buy_rejects_missing_event(setup):
    """Orphaned market (no parent event) must fail loudly, not with cryptic KeyError.

    FK is enforced in production, so this situation only arises during migration
    or manual recovery (PRAGMA foreign_keys = OFF). Defense in depth.
    """
    db, wallet, pm, engine = setup
    db.conn.execute("PRAGMA foreign_keys = OFF")
    try:
        db.conn.execute("DELETE FROM events WHERE event_id='e1'")
        db.conn.commit()
        with _mock_price(0.5), pytest.raises(ValueError, match="event .* not found"):
            engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    finally:
        db.conn.execute("PRAGMA foreign_keys = ON")
    # No side effects.
    assert wallet.get_cash() == 100.0
    assert len(wallet.list_transactions()) == 0


def test_execute_buy_rejects_degenerate_price(setup):
    """price = 0 (free shares) or price = 1 (max cost) is not a sane execution price."""
    db, wallet, pm, engine = setup
    for bad in (0.0, 1.0):
        with _mock_price(bad), pytest.raises(ValueError, match="out of range"):
            engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    assert wallet.get_cash() == 100.0


def test_execute_sell_rejects_degenerate_price(setup):
    """Post-resolution exit should go through ResolutionHandler, not execute_sell."""
    db, wallet, pm, engine = setup
    with _mock_price(0.5):
        engine.execute_buy(market_id="m1", side="yes", shares=10.0)
    for bad in (0.0, 1.0):
        with _mock_price(bad), pytest.raises(ValueError, match="out of range"):
            engine.execute_sell(market_id="m1", side="yes", shares=5.0)
    # Position unchanged.
    assert pm.get_position("m1", "yes")["shares"] == 10.0


def test_execute_buy_invalid_side(setup):
    db, wallet, pm, engine = setup
    with pytest.raises(ValueError, match="side"):
        engine.execute_buy(market_id="m1", side="maybe", shares=10.0)


def test_execute_buy_non_positive_shares(setup):
    db, wallet, pm, engine = setup
    with pytest.raises(ValueError, match="shares"):
        engine.execute_buy(market_id="m1", side="yes", shares=0)
    with pytest.raises(ValueError, match="shares"):
        engine.execute_buy(market_id="m1", side="yes", shares=-1.0)
