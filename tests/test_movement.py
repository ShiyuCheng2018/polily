from scanner.movement import MovementSignals, MovementResult


def test_movement_signals_defaults():
    s = MovementSignals()
    assert s.price_z_score == 0.0
    assert s.volume_ratio == 0.0
    assert s.book_imbalance == 0.0
    assert s.trade_concentration == 0.0
    assert s.open_interest_delta == 0.0


def test_movement_result_label():
    r = MovementResult(magnitude=80.0, quality=75.0)
    assert r.label == "consensus"

    r2 = MovementResult(magnitude=80.0, quality=30.0)
    assert r2.label == "whale_move"

    r3 = MovementResult(magnitude=30.0, quality=75.0)
    assert r3.label == "slow_build"

    r4 = MovementResult(magnitude=30.0, quality=30.0)
    assert r4.label == "noise"


def test_movement_result_should_trigger():
    r = MovementResult(magnitude=80.0, quality=75.0)
    assert r.should_trigger(m_threshold=70, q_threshold=60) is True

    r2 = MovementResult(magnitude=80.0, quality=30.0)
    assert r2.should_trigger(m_threshold=70, q_threshold=60) is False


def test_movement_result_cooldown_seconds():
    assert MovementResult(magnitude=75.0, quality=50.0).cooldown_seconds == 1800  # 30min
    assert MovementResult(magnitude=85.0, quality=50.0).cooldown_seconds == 600   # 10min
    assert MovementResult(magnitude=95.0, quality=50.0).cooldown_seconds == 180   # 3min
