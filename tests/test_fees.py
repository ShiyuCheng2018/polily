import pytest

from scanner.core.fees import CATEGORY_FEE_RATES, calculate_taker_fee


@pytest.mark.parametrize("category,expected_rate", [
    ("Crypto", 0.072),
    ("Sports", 0.03),
    ("Finance", 0.04),
    ("Politics", 0.04),
    ("Tech", 0.04),
    ("Economics", 0.05),
    ("Culture", 0.05),
    ("Weather", 0.05),
    ("Other", 0.05),
    ("Geopolitics", 0.0),
    ("World Events", 0.0),
])
def test_category_rates(category, expected_rate):
    assert CATEGORY_FEE_RATES[category] == expected_rate


def test_crypto_peak_fee_matches_official_example():
    # Docs example: 100 shares, Crypto, price=0.50 → $1.80
    assert calculate_taker_fee(100, 0.50, "Crypto") == 1.80


def test_crypto_fee_at_30_pct():
    # 100 × 0.072 × 0.30 × 0.70 = 1.512
    assert calculate_taker_fee(100, 0.30, "Crypto") == 1.512


def test_symmetry_30_and_70():
    # Fee at p=0.3 equals fee at p=0.7
    assert calculate_taker_fee(100, 0.30, "Crypto") == calculate_taker_fee(100, 0.70, "Crypto")


def test_zero_at_extremes():
    # Near extremes: positive but small
    assert calculate_taker_fee(100, 0.01, "Crypto") == pytest.approx(0.0713, abs=0.001)
    assert calculate_taker_fee(100, 0.99, "Crypto") == pytest.approx(0.0713, abs=0.001)
    # At boundaries: zero (0/1 means market resolved)
    assert calculate_taker_fee(100, 0.0, "Crypto") == 0.0
    assert calculate_taker_fee(100, 1.0, "Crypto") == 0.0
    assert calculate_taker_fee(0, 0.5, "Crypto") == 0.0


def test_geopolitics_always_zero():
    assert calculate_taker_fee(1000, 0.50, "Geopolitics") == 0.0
    assert calculate_taker_fee(1000, 0.10, "World Events") == 0.0


def test_unknown_category_uses_default():
    # Unknown categories fall back to 0.05 ("Other")
    fee_unknown = calculate_taker_fee(100, 0.5, "RandomMade-upCategory")
    fee_other = calculate_taker_fee(100, 0.5, "Other")
    assert fee_unknown == fee_other


def test_none_category_uses_default():
    assert calculate_taker_fee(100, 0.5, None) == calculate_taker_fee(100, 0.5, "Other")


def test_sports_vs_crypto_ratio():
    # Sports fee should be 0.03/0.072 ≈ 0.417 of crypto fee at same price
    assert calculate_taker_fee(100, 0.5, "Sports") / calculate_taker_fee(100, 0.5, "Crypto") == pytest.approx(0.03/0.072, abs=0.001)
