import pytest
from scanner.movement import MovementSignals, MovementResult
from scanner.movement_scorer import compute_movement_score
from scanner.config import MovementConfig


def test_all_zeros():
    signals = MovementSignals()
    config = MovementConfig()
    result = compute_movement_score(signals, "crypto", config)
    assert isinstance(result, MovementResult)
    assert result.magnitude == pytest.approx(0.0)
    assert result.quality == pytest.approx(0.0)
    assert result.label == "noise"


def test_crypto_high_fair_value_divergence():
    signals = MovementSignals(fair_value_divergence=0.15)  # 15% divergence
    config = MovementConfig()
    result = compute_movement_score(signals, "crypto", config)
    # fair_value_divergence: norm(0.15, max=0.20) = 75.0, weight 0.40 -> 30.0
    assert 25 < result.magnitude < 40


def test_unknown_market_type_uses_default():
    signals = MovementSignals(price_z_score=3.0)
    config = MovementConfig()
    result = compute_movement_score(signals, "unknown_type", config)
    assert result.magnitude > 0


def test_result_contains_signals():
    signals = MovementSignals(price_z_score=2.5)
    config = MovementConfig()
    result = compute_movement_score(signals, "crypto", config)
    assert result.signals.price_z_score == 2.5
