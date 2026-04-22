"""Pure computation helpers for TradeDialog Buy/Sell preview panels.

These helpers power the "≈ N股 · 赢可得 $X · 手续费 $Y" live previews
without dragging Textual widget setup into the test — fast, deterministic,
runs in <10ms per case.
"""

import pytest

from polily.tui.views._trade_preview import (
    compute_buy_preview,
    compute_sell_preview,
    shares_from_pct,
)

# --- Buy -----------------------------------------------------------------


def test_buy_preview_basic_crypto():
    """$10 at 55¢ YES, crypto_fees_v2 rate 0.072."""
    p = compute_buy_preview(
        amount_usd=10.0, price=0.55, fees_enabled=True, fee_rate=0.072,
    )
    assert p["shares"] == pytest.approx(18.1818, abs=1e-4)
    assert p["to_win"] == pytest.approx(18.1818, abs=1e-4)
    # fee = 18.1818 × 0.072 × 0.55 × 0.45
    assert p["fee"] == pytest.approx(0.324, abs=1e-3)
    assert p["cash_required"] == pytest.approx(10.324, abs=1e-3)


def test_buy_preview_fees_disabled_market():
    """Majority of Polymarket markets have fees_enabled=False → 0 fee."""
    p = compute_buy_preview(
        amount_usd=10.0, price=0.50, fees_enabled=False, fee_rate=None,
    )
    assert p["fee"] == 0.0
    assert p["cash_required"] == pytest.approx(10.0)


def test_buy_preview_enabled_but_rate_missing_returns_zero_fee():
    """Degenerate: gate on but no schedule — safe fallback is 0."""
    p = compute_buy_preview(
        amount_usd=10.0, price=0.50, fees_enabled=True, fee_rate=None,
    )
    assert p["fee"] == 0.0


def test_buy_preview_rejects_non_positive_amount():
    with pytest.raises(ValueError, match="amount"):
        compute_buy_preview(
            amount_usd=0.0, price=0.5, fees_enabled=True, fee_rate=0.072,
        )
    with pytest.raises(ValueError, match="amount"):
        compute_buy_preview(
            amount_usd=-1.0, price=0.5, fees_enabled=True, fee_rate=0.072,
        )


def test_buy_preview_rejects_edge_prices():
    """price must be in (0, 1) — extreme prices mean near-resolved market."""
    with pytest.raises(ValueError, match="price"):
        compute_buy_preview(
            amount_usd=10.0, price=0.0, fees_enabled=False, fee_rate=None,
        )
    with pytest.raises(ValueError, match="price"):
        compute_buy_preview(
            amount_usd=10.0, price=1.0, fees_enabled=False, fee_rate=None,
        )


# --- Sell ----------------------------------------------------------------


def test_sell_preview_profit_on_crypto_market():
    """Bought 20@0.50, sell 15@0.60 with crypto_fees_v2 (0.072)."""
    p = compute_sell_preview(
        shares=15.0, price=0.60,
        fees_enabled=True, fee_rate=0.072, avg_cost=0.50,
    )
    assert p["proceeds"] == pytest.approx(9.0)
    # fee = 15 × 0.072 × 0.60 × 0.40 = 0.2592
    assert p["fee"] == pytest.approx(0.2592, abs=1e-4)
    assert p["net_received"] == pytest.approx(9.0 - 0.2592, abs=1e-4)
    # realized = (0.60 - 0.50) × 15 = 1.50
    assert p["realized_pnl"] == pytest.approx(1.50)


def test_sell_preview_fees_disabled_keeps_net_equal_to_proceeds():
    """Common path (fees off) — net == proceeds (no Polymarket cut)."""
    p = compute_sell_preview(
        shares=10.0, price=0.60,
        fees_enabled=False, fee_rate=None, avg_cost=0.50,
    )
    assert p["fee"] == 0.0
    assert p["net_received"] == p["proceeds"]
    assert p["realized_pnl"] == pytest.approx(1.0)


def test_sell_preview_loss():
    """Bought 20@0.60, sell 10@0.40, fees on."""
    p = compute_sell_preview(
        shares=10.0, price=0.40,
        fees_enabled=True, fee_rate=0.072, avg_cost=0.60,
    )
    assert p["realized_pnl"] == pytest.approx(-2.0)
    assert p["net_received"] < p["proceeds"]  # fee deducted


def test_sell_preview_rejects_non_positive_shares():
    with pytest.raises(ValueError, match="shares"):
        compute_sell_preview(
            shares=0.0, price=0.5,
            fees_enabled=False, fee_rate=None, avg_cost=0.5,
        )


# --- Percent → shares ----------------------------------------------------


def test_shares_from_pct_basic():
    assert shares_from_pct(holdings=100.0, pct=25) == pytest.approx(25.0)
    assert shares_from_pct(holdings=100.0, pct=50) == pytest.approx(50.0)
    assert shares_from_pct(holdings=100.0, pct=100) == pytest.approx(100.0)


def test_shares_from_pct_fractional_holdings():
    """Fractional holdings (Polymarket allows non-integer shares)."""
    assert shares_from_pct(holdings=18.1818, pct=50) == pytest.approx(9.0909, abs=1e-4)


def test_shares_from_pct_rejects_invalid_pct():
    with pytest.raises(ValueError, match="pct"):
        shares_from_pct(holdings=100.0, pct=0)
    with pytest.raises(ValueError, match="pct"):
        shares_from_pct(holdings=100.0, pct=101)
