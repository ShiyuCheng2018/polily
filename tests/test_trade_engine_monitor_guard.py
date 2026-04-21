"""`ScanService.execute_buy` / `execute_sell` refuse trades on unmonitored events.

Policy lives in the service layer (not `TradeEngine`) — engine stays a
pure atomic primitive. Any new caller (e.g. a live-money trading
service) MUST route through the service to inherit this guard, or
replicate the check.

Invariant (enforced in `toggle_monitor`): positions exist → monitor is
on. So on a normal flow, sell should never hit an unmonitored event;
this test locks in the defence-in-depth assertion that surfaces DB
drift anyway.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scanner.core.db import PolilyDB
from scanner.core.event_store import EventRow, MarketRow, upsert_event, upsert_market
from scanner.core.monitor_store import upsert_event_monitor
from scanner.tui.service import MonitorRequiredError, ScanService


@pytest.fixture
def svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(
        EventRow(event_id="ev1", title="Test", slug="s", updated_at="now"),
        db,
    )
    upsert_market(
        MarketRow(
            market_id="m1", event_id="ev1", question="Q",
            yes_price=0.5, updated_at="now",
        ),
        db,
    )
    yield ScanService(config=cfg, db=db)
    db.close()


def test_execute_buy_raises_when_monitor_off(svc):
    upsert_event_monitor("ev1", auto_monitor=False, db=svc.db)
    with pytest.raises(MonitorRequiredError) as excinfo:
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    assert excinfo.value.event_id == "ev1"


def test_execute_buy_raises_when_no_monitor_row(svc):
    """No monitor row at all = never monitored = rejected."""
    # Don't seed a monitor row.
    with pytest.raises(MonitorRequiredError):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)


def test_execute_sell_raises_when_monitor_off(svc):
    """Defence-in-depth: sell shouldn't reach here under the invariant,
    but if DB is externally corrupted, surface it."""
    svc.db.conn.execute(
        "INSERT INTO positions (event_id, market_id, side, shares, avg_cost, "
        "cost_basis, title, opened_at, updated_at) "
        "VALUES ('ev1', 'm1', 'yes', 10.0, 0.5, 5.0, 'Q', 'now', 'now')",
    )
    upsert_event_monitor("ev1", auto_monitor=False, db=svc.db)
    svc.db.conn.commit()

    with pytest.raises(MonitorRequiredError) as excinfo:
        svc.execute_sell(market_id="m1", side="yes", shares=5.0)
    assert excinfo.value.event_id == "ev1"


def test_execute_buy_works_when_monitor_on(svc):
    """Regression: monitored event trades execute without raising."""
    upsert_event_monitor("ev1", auto_monitor=True, db=svc.db)
    with patch.object(svc.trade_engine, "_fetch_live_price", return_value=0.5):
        result = svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    assert result is not None


def test_execute_sell_works_when_monitor_on(svc):
    """Regression: monitored event sells execute without raising."""
    upsert_event_monitor("ev1", auto_monitor=True, db=svc.db)
    with patch.object(svc.trade_engine, "_fetch_live_price", return_value=0.5):
        svc.execute_buy(market_id="m1", side="yes", shares=10.0)
    with patch.object(svc.trade_engine, "_fetch_live_price", return_value=0.5):
        result = svc.execute_sell(market_id="m1", side="yes", shares=5.0)
    assert result is not None


def test_trade_engine_itself_is_not_guarded(svc):
    """Architectural contract: TradeEngine is a pure atomic primitive.
    It does NOT check monitor; the service layer's policy guard does.
    Any future live-trading service MUST replicate the service-level
    check OR route through ScanService.
    """
    # Don't seed monitor. Direct engine call should NOT raise.
    with patch.object(svc.trade_engine, "_fetch_live_price", return_value=0.5):
        result = svc.trade_engine.execute_buy(
            market_id="m1", side="yes", shares=10.0,
        )
    assert result is not None
