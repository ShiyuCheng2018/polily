"""Unit tests for polily.scan.event_scoring.compute_implied_fair_values.

AF-3 (v0.11.7): negRisk events have completeness Σ(yes_prices) ≈ 1.0,
so each market's implied fair value is `1 - Σ(other markets' yes_price)`.
This gives the agent a zero-model-risk structural anchor for non-crypto
events, replacing dependence on flaky WebSearch options-implied-prob.

Edge cases tested:
- Happy path: 3-market negRisk event
- Single-market negRisk: skip (1 - Σ() degenerates to 1, not meaningful)
- Market with None yes_price: skip that market in the sum
- < 2 valid markets remaining (after None filter): skip entire event
- Non-negRisk event: returns empty dict (no completeness constraint)
- Extreme values (yes_price < 0.005 or > 0.995): include in sum (raw)
"""
from __future__ import annotations

from polily.scan.event_scoring import compute_implied_fair_values


class _StubEvent:
    """Minimal EventRow shim for unit tests."""

    def __init__(self, *, neg_risk: bool):
        self.neg_risk = neg_risk


class _StubMarket:
    """Minimal Market shim with just market_id + yes_price."""

    def __init__(self, market_id: str, yes_price: float | None):
        self.market_id = market_id
        self.yes_price = yes_price


def test_neg_risk_three_markets_happy_path():
    """Standard 3-market negRisk event with Σ < 1.0 (under-priced).

    m1=0.5, m2=0.3, m3=0.1, total=0.9
    implied_fair[m1] = 1 - (0.3 + 0.1) = 0.6
    implied_fair[m2] = 1 - (0.5 + 0.1) = 0.4
    implied_fair[m3] = 1 - (0.5 + 0.3) = 0.2
    """
    event = _StubEvent(neg_risk=True)
    markets = [
        _StubMarket("m1", 0.5),
        _StubMarket("m2", 0.3),
        _StubMarket("m3", 0.1),
    ]

    result = compute_implied_fair_values(event, markets)

    assert result == {
        "m1": 0.6,
        "m2": 0.4,
        "m3": 0.2,
    }


def test_neg_risk_overround_event():
    """3-market negRisk with Σ > 1.0 (over-priced; sum 1.1).

    m1=0.5, m2=0.4, m3=0.2, total=1.1
    implied_fair[m1] = 1 - (0.4 + 0.2) = 0.4 → m1 over-priced by 0.1
    implied_fair[m2] = 1 - (0.5 + 0.2) = 0.3
    implied_fair[m3] = 1 - (0.5 + 0.4) = 0.1
    """
    event = _StubEvent(neg_risk=True)
    markets = [
        _StubMarket("m1", 0.5),
        _StubMarket("m2", 0.4),
        _StubMarket("m3", 0.2),
    ]

    result = compute_implied_fair_values(event, markets)

    assert result == {"m1": 0.4, "m2": 0.3, "m3": 0.1}


def test_non_neg_risk_returns_empty():
    """Non-negRisk events have no completeness constraint, so no
    implied fair values are computed."""
    event = _StubEvent(neg_risk=False)
    markets = [
        _StubMarket("m1", 0.5),
        _StubMarket("m2", 0.3),
    ]

    result = compute_implied_fair_values(event, markets)

    assert result == {}


def test_single_market_neg_risk_skipped():
    """1-market negRisk degenerates to 1 - 0 = 1 (the one market's
    implied fair = 1.0, which is meaningless). Skip entire event."""
    event = _StubEvent(neg_risk=True)
    markets = [_StubMarket("m1", 0.5)]

    result = compute_implied_fair_values(event, markets)

    assert result == {}


def test_none_price_market_excluded_from_sum():
    """Market with yes_price=None drops out of the sum but other
    markets still get their implied fair computed against the remaining."""
    event = _StubEvent(neg_risk=True)
    markets = [
        _StubMarket("m1", 0.5),
        _StubMarket("m2", None),  # excluded
        _StubMarket("m3", 0.3),
    ]

    result = compute_implied_fair_values(event, markets)

    # Sum of valid (m1+m3) = 0.8
    # implied_fair[m1] = 1 - 0.3 = 0.7
    # implied_fair[m3] = 1 - 0.5 = 0.5
    # m2 excluded — no key
    assert result == {"m1": 0.7, "m3": 0.5}
    assert "m2" not in result


def test_too_few_valid_markets_skips_event():
    """If after None filtering only 1 valid market remains, skip the
    entire event (same reasoning as single-market case)."""
    event = _StubEvent(neg_risk=True)
    markets = [
        _StubMarket("m1", 0.5),
        _StubMarket("m2", None),
        _StubMarket("m3", None),
    ]

    result = compute_implied_fair_values(event, markets)

    assert result == {}


def test_extreme_values_included_raw():
    """yes_price < 0.005 or > 0.995 are not clamped — agent sees raw
    values and decides if they're meaningful. e.g., a 99.9%-likely
    leader still sums into the others' implied fair calculation."""
    event = _StubEvent(neg_risk=True)
    markets = [
        _StubMarket("m1", 0.999),  # near-certain leader
        _StubMarket("m2", 0.001),  # near-zero
        _StubMarket("m3", 0.05),   # outside-chance
    ]

    result = compute_implied_fair_values(event, markets)

    # total = 1.05 (slight overround)
    # implied_fair[m1] = 1 - (0.001 + 0.05) = 0.949
    # implied_fair[m2] = 1 - (0.999 + 0.05) = -0.049 → negative is allowed
    # implied_fair[m3] = 1 - (0.999 + 0.001) = 0.0
    assert result == {"m1": 0.949, "m2": -0.049, "m3": 0.0}


def test_returns_floats_rounded_to_4_places():
    """Output is rounded to 4 decimal places to match yes_price storage
    precision and avoid trailing-digit noise in score_breakdown JSON."""
    event = _StubEvent(neg_risk=True)
    markets = [
        _StubMarket("m1", 1.0 / 3),  # 0.333... → 0.3333
        _StubMarket("m2", 1.0 / 3),
        _StubMarket("m3", 1.0 / 3),
    ]

    result = compute_implied_fair_values(event, markets)

    # Each implied_fair = 1 - 2/3 = 0.3333 (rounded)
    for v in result.values():
        # Verify it's a plain float, rounded to 4 decimals.
        assert isinstance(v, float)
        # Verify rounding precision.
        assert abs(v * 10000 - round(v * 10000)) < 1e-9


def test_empty_markets_returns_empty():
    """Defensive: empty markets list returns empty dict (don't crash)."""
    event = _StubEvent(neg_risk=True)
    result = compute_implied_fair_values(event, [])
    assert result == {}
