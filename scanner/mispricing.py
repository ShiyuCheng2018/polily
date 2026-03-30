"""Mispricing detection: compare market price vs theoretical fair value.

For crypto threshold markets: use log-normal model with realized volatility.
For all markets: check multi-outcome price sum consistency.
"""

import math
from dataclasses import dataclass

from scanner.config import MispricingConfig
from scanner.models import Market


@dataclass
class MispricingResult:
    signal: str  # "none", "weak", "moderate", "strong"
    direction: str | None = None  # "overpriced", "underpriced", None
    theoretical_fair_value: float | None = None
    deviation_pct: float | None = None
    details: str | None = None
    multi_outcome_flag: bool = False
    model_confidence: str | None = None  # "high", "medium", "low"


def normal_cdf(x: float) -> float:
    """Standard normal cumulative distribution function using math.erf."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def compute_crypto_fair_value(
    current_price: float,
    threshold_price: float,
    days_to_resolution: float,
    annual_volatility: float,
) -> float:
    """Estimate P(price > threshold at resolution) using log-normal model.

    Uses the Black-Scholes-style formula for a cash-or-nothing binary option:
    P(S_T > K) = N(d2) where d2 = (ln(S/K) + (- σ²/2)T) / (σ√T)

    Assumes zero drift (risk-neutral for prediction market context).
    """
    if days_to_resolution <= 0:
        return 1.0 if current_price >= threshold_price else 0.0

    t = days_to_resolution / 365.0
    sigma = annual_volatility
    sigma_sqrt_t = sigma * math.sqrt(t)

    if sigma_sqrt_t < 1e-10:
        return 1.0 if current_price >= threshold_price else 0.0

    d2 = (math.log(current_price / threshold_price) - 0.5 * sigma * sigma * t) / sigma_sqrt_t
    return normal_cdf(d2)


def detect_mispricing(
    market: Market,
    config: MispricingConfig,
    current_underlying_price: float | None = None,
    threshold_price: float | None = None,
    annual_volatility: float | None = None,
    vol_source: str | None = None,
    vol_data_days: int | None = None,
) -> MispricingResult:
    """Detect potential mispricing for a market.

    For crypto_threshold markets with price data: compare vol-model fair value vs market price.
    For all markets: check multi-outcome sum deviation.
    """
    result = MispricingResult(signal="none")

    if not config.enabled:
        return result

    # Multi-outcome consistency check
    if config.multi_outcome.enabled and market.event_outcome_prices_sum is not None:
        deviation = abs(market.event_outcome_prices_sum - 1.0)
        if deviation > config.multi_outcome.max_sum_deviation:
            result.multi_outcome_flag = True

    # Crypto threshold mispricing
    if (
        market.market_type == "crypto_threshold"
        and market.yes_price is not None
        and current_underlying_price is not None
        and threshold_price is not None
        and annual_volatility is not None
        and market.days_to_resolution is not None
    ):
        fair_value = compute_crypto_fair_value(
            current_price=current_underlying_price,
            threshold_price=threshold_price,
            days_to_resolution=market.days_to_resolution,
            annual_volatility=annual_volatility,
        )
        result.theoretical_fair_value = round(fair_value, 4)

        deviation = abs(market.yes_price - fair_value)
        result.deviation_pct = round(deviation, 4)

        min_dev = config.crypto.min_deviation_pct
        if deviation >= min_dev * 1.5:
            result.signal = "strong"
        elif deviation >= min_dev:
            result.signal = "moderate"
        elif deviation >= min_dev * 0.5:
            result.signal = "weak"

        # Dual-factor model confidence: time + vol data quality
        days = market.days_to_resolution or 0
        vdays = vol_data_days or 0
        vsrc = vol_source or "unknown"

        if vsrc == "fallback_default" or vdays < 5:
            result.model_confidence = "low"
        elif days >= 3 and vdays >= 20:
            result.model_confidence = "high"
        elif days >= 1 and vdays >= 10:
            result.model_confidence = "medium"
        else:
            result.model_confidence = "low"

        # Low confidence: kill signal entirely (don't mislead)
        if result.model_confidence == "low":
            result.signal = "none"

        direction = "overpriced" if market.yes_price > fair_value else "underpriced"
        direction_cn = "被高估" if direction == "overpriced" else "被低估"
        # Only set direction when confidence is sufficient
        if result.model_confidence != "low":
            result.direction = direction
        vol_note = f", 波动率: {annual_volatility:.0%} ({vsrc})" if annual_volatility else ""
        conf_note = f", 置信度: {result.model_confidence}"
        result.details = (
            f"模型估值 {fair_value:.2f}, 市价 {market.yes_price:.2f}, "
            f"偏差 {deviation:.1%} — YES {direction_cn}{vol_note}{conf_note}"
        )

    return result
