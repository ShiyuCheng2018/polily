"""Tests for compute_wallet_overview — pure balance aggregation."""

import pytest

from polily.tui.views._wallet_overview import compute_wallet_overview


def _snap(**kw) -> dict:
    defaults = {
        "cash_usd": 100.0, "starting_balance": 100.0,
        "topup_total": 0.0, "withdraw_total": 0.0,
        "cumulative_realized_pnl": 0.0,
    }
    defaults.update(kw)
    return defaults


def test_overview_fresh_wallet():
    """No positions, no transactions."""
    ov = compute_wallet_overview(
        snapshot=_snap(), positions=[], price_lookup=lambda m, s: None,
    )
    assert ov["cash_usd"] == 100.0
    assert ov["equity"] == 100.0
    assert ov["net_inflow"] == 100.0
    assert ov["total_pnl"] == 0.0
    assert ov["roi_pct"] == 0.0
    assert ov["open_positions_count"] == 0


def test_overview_with_position_at_cost():
    """Position at current price = avg_cost → unrealized 0."""
    positions = [{
        "market_id": "m1", "side": "yes",
        "shares": 20.0, "avg_cost": 0.5, "cost_basis": 10.0,
    }]
    # Cash is $100 - $10 (bought position) = $90 (ignoring fees for math clarity).
    snap = _snap(cash_usd=90.0)
    ov = compute_wallet_overview(
        snapshot=snap, positions=positions,
        price_lookup=lambda m, s: 0.5,  # current = avg_cost
    )
    assert ov["positions_market_value"] == pytest.approx(10.0)
    assert ov["equity"] == pytest.approx(100.0)
    assert ov["unrealized_pnl"] == pytest.approx(0.0)
    assert ov["total_pnl"] == pytest.approx(0.0)
    assert ov["open_positions_count"] == 1


def test_overview_with_unrealized_gain():
    """Market moved up → unrealized +, equity up."""
    positions = [{
        "market_id": "m1", "side": "yes",
        "shares": 20.0, "avg_cost": 0.5, "cost_basis": 10.0,
    }]
    snap = _snap(cash_usd=90.0)
    ov = compute_wallet_overview(
        snapshot=snap, positions=positions,
        price_lookup=lambda m, s: 0.6,  # +10¢
    )
    # market_value = 20 × 0.6 = 12; unrealized = 12 - 10 = 2
    assert ov["positions_market_value"] == pytest.approx(12.0)
    assert ov["unrealized_pnl"] == pytest.approx(2.0)
    assert ov["equity"] == pytest.approx(102.0)
    assert ov["total_pnl"] == pytest.approx(2.0)
    assert ov["roi_pct"] == pytest.approx(2.0)


def test_overview_with_realized_pnl():
    """Cumulative realized flows through from snapshot."""
    snap = _snap(cash_usd=102.5, cumulative_realized_pnl=2.5)
    ov = compute_wallet_overview(
        snapshot=snap, positions=[], price_lookup=lambda m, s: None,
    )
    assert ov["realized_pnl"] == pytest.approx(2.5)
    assert ov["total_pnl"] == pytest.approx(2.5)


def test_overview_topup_withdraw_affects_net_inflow():
    """ROI denominator reflects user cash movements."""
    snap = _snap(
        cash_usd=200.0, starting_balance=100.0,
        topup_total=200.0, withdraw_total=50.0,
    )
    ov = compute_wallet_overview(
        snapshot=snap, positions=[], price_lookup=lambda m, s: None,
    )
    # net_inflow = 100 + 200 - 50 = 250; equity = 200; total_pnl = -50
    assert ov["net_inflow"] == pytest.approx(250.0)
    assert ov["total_pnl"] == pytest.approx(-50.0)
    assert ov["roi_pct"] == pytest.approx(-20.0)


def test_overview_price_unavailable_values_at_cost():
    """When price_lookup returns None, the position contributes its cost basis.

    Keeps equity from swinging wildly on transient price-fetch failures.
    """
    positions = [{
        "market_id": "m1", "side": "yes",
        "shares": 10.0, "avg_cost": 0.5, "cost_basis": 5.0,
    }]
    snap = _snap(cash_usd=95.0)
    ov = compute_wallet_overview(
        snapshot=snap, positions=positions,
        price_lookup=lambda m, s: None,  # price unavailable
    )
    assert ov["positions_market_value"] == pytest.approx(5.0)
    assert ov["unrealized_pnl"] == pytest.approx(0.0)


def test_overview_roi_pct_zero_when_net_inflow_zero():
    """Edge: user withdrew everything → net_inflow = 0 → roi_pct guarded from div-by-zero."""
    snap = _snap(
        cash_usd=0.0, starting_balance=100.0,
        topup_total=0.0, withdraw_total=100.0,
    )
    ov = compute_wallet_overview(
        snapshot=snap, positions=[], price_lookup=lambda m, s: None,
    )
    assert ov["net_inflow"] == 0.0
    assert ov["roi_pct"] == 0.0  # not infinity, not NaN
