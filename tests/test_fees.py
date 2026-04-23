"""Tests for Polymarket taker fee — now driven by market.feesEnabled + feeSchedule.rate.

Prior version of this module mapped event category → rate using a hardcoded
table. POC on 2026-04-18 against live Gamma revealed that category does not
drive fees at all — `market.feesEnabled` + `market.feeSchedule.rate` do.
Out of 2,525 sampled markets, 2,425 had fees DISABLED (Politics / Sports /
Geopolitics majors all zero). Only short-term crypto + sports markets had
fees enabled, with rates coming from feeSchedule.rate directly.
"""

import pytest

from polily.core.fees import calculate_taker_fee


def test_fees_disabled_returns_zero():
    """The authoritative gate. If Polymarket's market.feesEnabled is false,
    we must not charge anything — regardless of any other field.
    """
    assert calculate_taker_fee(
        shares=100, price=0.5, fees_enabled=False, fee_rate=0.072,
    ) == 0.0
    # Even with a non-zero rate present: gate wins.
    assert calculate_taker_fee(
        shares=100, price=0.7, fees_enabled=False, fee_rate=0.03,
    ) == 0.0


def test_fees_enabled_but_rate_missing_returns_zero():
    """Degenerate: enabled=True but no rate. Treat as 0 so we don't guess."""
    assert calculate_taker_fee(
        shares=100, price=0.5, fees_enabled=True, fee_rate=None,
    ) == 0.0


def test_crypto_v2_peak_fee_matches_fee_schedule():
    """feeSchedule.rate=0.072 at price 0.5: 100 × 0.072 × 0.5 × 0.5 = 1.80.

    This is the exact value Polymarket's own docs cite for crypto fees.
    """
    assert calculate_taker_fee(
        shares=100, price=0.5, fees_enabled=True, fee_rate=0.072,
    ) == pytest.approx(1.80)


def test_sports_v2_rate():
    """Live market 2013686 etc. carry feeSchedule.rate=0.03 for sports_fees_v2."""
    # 100 × 0.03 × 0.5 × 0.5 = 0.75
    assert calculate_taker_fee(
        shares=100, price=0.5, fees_enabled=True, fee_rate=0.03,
    ) == pytest.approx(0.75)


def test_symmetry_around_half():
    """fee(p) == fee(1-p) for the quadratic curve."""
    a = calculate_taker_fee(shares=100, price=0.3, fees_enabled=True, fee_rate=0.072)
    b = calculate_taker_fee(shares=100, price=0.7, fees_enabled=True, fee_rate=0.072)
    assert a == pytest.approx(b)


def test_edge_prices_return_zero():
    """price ∈ {0, 1} means the market is already resolved — no fee."""
    assert calculate_taker_fee(shares=100, price=0.0, fees_enabled=True, fee_rate=0.072) == 0.0
    assert calculate_taker_fee(shares=100, price=1.0, fees_enabled=True, fee_rate=0.072) == 0.0


def test_zero_shares_returns_zero():
    assert calculate_taker_fee(shares=0, price=0.5, fees_enabled=True, fee_rate=0.072) == 0.0
    assert calculate_taker_fee(shares=-1, price=0.5, fees_enabled=True, fee_rate=0.072) == 0.0


def test_rounding_to_four_decimals():
    """Keep wallet_transactions.fee_usd precise to cent-fragments without drift."""
    # 17.2661870503597 × 0.072 × 0.7 × 0.3 ≈ 0.26097...
    fee = calculate_taker_fee(
        shares=17.2661870503597, price=0.7, fees_enabled=True, fee_rate=0.072,
    )
    assert fee == round(17.2661870503597 * 0.072 * 0.7 * 0.3, 4)


def test_iran_scenario_is_now_zero_fee():
    """Regression for the bug that triggered this refactor: the 'US x Iran
    peace deal' market has feesEnabled=false — the user paid $0.18 on a $12
    buy under the old category-based path, which should have been $0.
    """
    fee = calculate_taker_fee(
        shares=17.266, price=0.7, fees_enabled=False, fee_rate=None,
    )
    assert fee == 0.0
