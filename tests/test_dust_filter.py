"""Dust-position filter: positions below `DUST_SHARE_THRESHOLD` shares are
hidden from display surfaces (paper_status, wallet balance card, event
detail PositionPanel) but remain in the DB and in accounting layers.

A "dust" position is a tiny leftover after partial sells with decimal
arithmetic — e.g., 0.02 shares worth < $0.02. Showing them misleads the
user into thinking they have an open bet when they effectively don't.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import MarketRow, upsert_event, upsert_market
from polily.core.monitor_store import upsert_event_monitor
from polily.core.positions import DUST_SHARE_THRESHOLD, is_dust_position
from polily.tui.service import PolilyService
from tests.conftest import make_event


def _svc(tmp_path):
    cfg = MagicMock()
    cfg.wallet.starting_balance = 100.0
    cfg.paper_trading.default_position_size_usd = 20
    cfg.paper_trading.assumed_round_trip_friction_pct = 0.04
    db = PolilyDB(tmp_path / "t.db")
    upsert_event(make_event(event_id="ev1"), db)
    upsert_market(
        MarketRow(
            market_id="m1", event_id="ev1", question="Q",
            yes_price=0.5, updated_at="now",
        ),
        db,
    )
    upsert_event_monitor("ev1", auto_monitor=True, db=db)
    return PolilyService(config=cfg, db=db), db


def _insert_raw_position(db, *, shares: float, market_id: str = "m1"):
    """Insert a position directly (bypassing TradeEngine) so we can seed
    arbitrary share counts including sub-threshold dust values."""
    db.conn.execute(
        "INSERT INTO positions (event_id, market_id, side, shares, avg_cost, "
        "cost_basis, title, opened_at, updated_at) "
        "VALUES ('ev1', ?, 'yes', ?, 0.5, ?, 'Q', 'now', 'now')",
        (market_id, shares, shares * 0.5),
    )
    db.conn.commit()


# ---------------------- Pure helper ----------------------


def test_is_dust_position_below_threshold():
    assert is_dust_position({"shares": 0.05})
    assert is_dust_position({"shares": DUST_SHARE_THRESHOLD - 0.001})


def test_is_dust_position_at_or_above_threshold():
    assert not is_dust_position({"shares": DUST_SHARE_THRESHOLD})
    assert not is_dust_position({"shares": 1.0})
    assert not is_dust_position({"shares": 10.5})


def test_is_dust_position_handles_bad_input():
    assert not is_dust_position({})  # no shares key
    assert not is_dust_position({"shares": None})


# ---------------------- Service integration ----------------------


def test_get_open_trades_filters_dust(tmp_path):
    """paper_status list hides dust positions."""
    svc, db = _svc(tmp_path)
    _insert_raw_position(db, shares=10.0, market_id="m1")
    # Add a second market with a dust position.
    upsert_market(
        MarketRow(market_id="m_dust", event_id="ev1", question="Q2",
                  yes_price=0.5, updated_at="now"),
        db,
    )
    _insert_raw_position(db, shares=0.02, market_id="m_dust")

    trades = svc.get_open_trades()
    market_ids = [t["market_id"] for t in trades]
    assert "m1" in market_ids
    assert "m_dust" not in market_ids, "dust position leaked into open trades"


def test_get_all_positions_filters_dust(tmp_path):
    """Wallet balance card '持仓' count hides dust."""
    svc, db = _svc(tmp_path)
    _insert_raw_position(db, shares=10.0, market_id="m1")
    upsert_market(
        MarketRow(market_id="m_dust", event_id="ev1", question="Q2",
                  yes_price=0.5, updated_at="now"),
        db,
    )
    _insert_raw_position(db, shares=0.02, market_id="m_dust")

    positions = svc.get_all_positions()
    market_ids = [p["market_id"] for p in positions]
    assert "m1" in market_ids
    assert "m_dust" not in market_ids


def test_event_detail_trades_hides_dust(tmp_path):
    """EventDetailView's PositionPanel feed (`detail['trades']`) hides dust."""
    svc, db = _svc(tmp_path)
    _insert_raw_position(db, shares=10.0, market_id="m1")
    upsert_market(
        MarketRow(market_id="m_dust", event_id="ev1", question="Q2",
                  yes_price=0.5, updated_at="now"),
        db,
    )
    _insert_raw_position(db, shares=0.02, market_id="m_dust")

    detail = svc.get_event_detail("ev1")
    market_ids = [t["market_id"] for t in detail["trades"]]
    assert "m1" in market_ids
    assert "m_dust" not in market_ids


# ---------------------- Accounting layer preserves dust ----------------------


def test_position_manager_get_all_positions_keeps_dust(tmp_path):
    """Core `PositionManager` (accounting) is NOT filtered — dust is real
    DB state. Only service-layer display methods filter."""
    svc, db = _svc(tmp_path)
    _insert_raw_position(db, shares=0.02, market_id="m1")

    # Core query returns dust row.
    raw_positions = svc.positions.get_all_positions()
    assert len(raw_positions) == 1
    assert raw_positions[0]["shares"] == pytest.approx(0.02)


def test_event_position_count_includes_dust(tmp_path):
    """`get_event_position_count` used by monitor toggle & trade guard
    must count dust — it's still the user's (tiny) skin in the game."""
    svc, db = _svc(tmp_path)
    _insert_raw_position(db, shares=0.02, market_id="m1")
    assert svc.get_event_position_count("ev1") == 1
