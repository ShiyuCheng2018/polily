"""Compute dual-dimension movement score from raw signals."""

from scanner.config import MovementConfig
from scanner.movement import MovementResult, MovementSignals


def _normalize(value: float, max_val: float = 1.0) -> float:
    """Normalize a raw signal to 0-100 scale."""
    return min(abs(value) / max_val * 100, 100)


# Signal normalization ranges (signal_name -> max_for_100)
_NORM_RANGES: dict[str, float] = {
    "price_z_score": 3.0,
    "volume_ratio": 5.0,
    "book_imbalance": 0.8,
    "trade_concentration": 0.8,
    "open_interest_delta": 0.5,
    "fair_value_divergence": 0.20,
    "underlying_z_score": 3.0,
    "cross_divergence": 0.8,
    "sustained_drift": 1.0,
    "time_decay_adjusted_move": 0.3,
    "correlated_asset_move": 3.0,
    "volume_price_confirmation": 1.0,
}


def compute_movement_score(
    signals: MovementSignals,
    market_type: str,
    config: MovementConfig,
) -> MovementResult:
    """Compute dual-dimension movement score using market-type-specific weights."""
    weights = config.weights.get(market_type, config.weights.get("default"))
    if weights is None:
        weights = config.weights["default"]

    signals_dict = signals.model_dump()

    # Compute magnitude
    magnitude = 0.0
    for signal_name, weight in weights.magnitude.items():
        raw_val = signals_dict.get(signal_name, 0.0)
        norm_max = _NORM_RANGES.get(signal_name, 1.0)
        magnitude += weight * _normalize(raw_val, norm_max)

    # Compute quality
    quality = 0.0
    for signal_name, weight in weights.quality.items():
        raw_val = signals_dict.get(signal_name, 0.0)
        norm_max = _NORM_RANGES.get(signal_name, 1.0)
        quality += weight * _normalize(raw_val, norm_max)

    return MovementResult(
        magnitude=round(magnitude, 2),
        quality=round(quality, 2),
        signals=signals,
    )
