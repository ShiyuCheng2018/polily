"""Task 3.0: ScanService exposes wallet/positions/trade_engine + proxy methods.

Contract: TUI views (Task 3.1-3.3) reach wallet state through ScanService
attributes + thin proxy methods. No direct DB access from view code.
"""

from unittest.mock import patch

import pytest

from scanner.core.config import ScannerConfig
from scanner.core.db import PolilyDB
from scanner.core.positions import PositionManager
from scanner.core.trade_engine import TradeEngine
from scanner.core.wallet import WalletService
from scanner.tui.service import ScanService


@pytest.fixture
def svc(tmp_path):
    db = PolilyDB(tmp_path / "t.db")
    db.conn.executescript(
        """
        INSERT INTO events (event_id,title,polymarket_category,updated_at)
            VALUES ('e1','E1','Crypto','t');
        INSERT INTO markets (market_id,event_id,question,clob_token_id_yes,clob_token_id_no,yes_price,updated_at)
            VALUES ('m1','e1','Q','tok_yes','tok_no',0.5,'t');
        """
    )
    db.conn.commit()
    return ScanService(config=ScannerConfig(), db=db)


def _mock_price(value: float):
    return patch(
        "scanner.core.trade_engine.TradeEngine._fetch_live_price",
        return_value=value,
    )


def test_service_exposes_wallet_position_engine(svc):
    """ScanService owns WalletService, PositionManager, TradeEngine as attributes."""
    assert isinstance(svc.wallet, WalletService)
    assert isinstance(svc.positions, PositionManager)
    assert isinstance(svc.trade_engine, TradeEngine)
    # Migration-seeded wallet singleton is reachable without extra init.
    assert svc.wallet.get_cash() == 100.0


def test_service_trade_engine_shares_wallet_and_positions(svc):
    """TradeEngine instance uses the same wallet/positions as svc.wallet/svc.positions."""
    assert svc.trade_engine.wallet is svc.wallet
    assert svc.trade_engine.positions is svc.positions


def test_service_proxies_wallet_methods(svc):
    """topup/withdraw/get_wallet_snapshot/get_wallet_transactions delegate to WalletService."""
    svc.topup(50.0)
    assert svc.wallet.get_cash() == pytest.approx(150.0)

    svc.withdraw(20.0)
    assert svc.wallet.get_cash() == pytest.approx(130.0)

    snap = svc.get_wallet_snapshot()
    assert snap["cash_usd"] == pytest.approx(130.0)
    assert snap["topup_total"] == pytest.approx(50.0)
    assert snap["withdraw_total"] == pytest.approx(20.0)

    txs = svc.get_wallet_transactions(limit=10)
    types = [t["type"] for t in txs]
    assert "TOPUP" in types
    assert "WITHDRAW" in types


def test_service_proxies_position_methods(svc):
    """get_all_positions / get_event_positions delegate to PositionManager."""
    # Initially empty
    assert svc.get_all_positions() == []
    assert svc.get_event_positions("e1") == []

    with _mock_price(0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)

    all_pos = svc.get_all_positions()
    assert len(all_pos) == 1
    assert all_pos[0]["market_id"] == "m1"
    assert all_pos[0]["side"] == "yes"
    assert all_pos[0]["shares"] == 10.0

    event_pos = svc.get_event_positions("e1")
    assert len(event_pos) == 1
    assert event_pos[0]["market_id"] == "m1"


def test_service_proxies_execute_buy_and_sell(svc):
    """execute_buy/execute_sell delegate to TradeEngine and mutate wallet+positions atomically."""
    with _mock_price(0.5):
        buy_result = svc.execute_buy(market_id="m1", side="yes", shares=20.0)
    assert buy_result["price"] == 0.5
    assert buy_result["cost"] == pytest.approx(10.0)
    assert svc.positions.get_position("m1", "yes")["shares"] == 20.0

    with _mock_price(0.6):
        sell_result = svc.execute_sell(market_id="m1", side="yes", shares=5.0)
    assert sell_result["price"] == 0.6
    assert sell_result["proceeds"] == pytest.approx(3.0)
    # bought 20@0.5 (avg_cost=0.5), sold 5@0.6 → realized = 5 * (0.6 - 0.5) = 0.5
    assert sell_result["realized_pnl"] == pytest.approx(0.5)
    assert svc.positions.get_position("m1", "yes")["shares"] == 15.0
