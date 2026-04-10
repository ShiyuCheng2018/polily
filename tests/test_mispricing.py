"""Tests for mispricing detection (crypto threshold vol model + multi-outcome check)."""

from datetime import UTC, datetime

from scanner.core.config import CryptoMispricingConfig, MispricingConfig, MultiOutcomeConfig
from scanner.scan.mispricing import (
    compute_crypto_fair_value,
    detect_mispricing,
    normal_cdf,
)
from tests.conftest import make_market


class TestNormalCdf:
    def test_zero(self):
        assert abs(normal_cdf(0) - 0.5) < 1e-10

    def test_positive(self):
        # N(1.96) ≈ 0.975
        assert abs(normal_cdf(1.96) - 0.975) < 0.001

    def test_negative(self):
        # N(-1.96) ≈ 0.025
        assert abs(normal_cdf(-1.96) - 0.025) < 0.001

    def test_large_positive(self):
        assert normal_cdf(5.0) > 0.999

    def test_large_negative(self):
        assert normal_cdf(-5.0) < 0.001


class TestCryptoFairValue:
    def test_at_the_money(self):
        """When current price equals threshold, probability should be ~0.50."""
        fv = compute_crypto_fair_value(
            current_price=88000,
            threshold_price=88000,
            days_to_resolution=3.0,
            annual_volatility=0.60,
        )
        assert abs(fv - 0.50) < 0.05

    def test_deep_in_the_money(self):
        """Current price well above threshold -> high probability."""
        fv = compute_crypto_fair_value(
            current_price=95000,
            threshold_price=88000,
            days_to_resolution=3.0,
            annual_volatility=0.60,
        )
        assert fv > 0.65

    def test_deep_out_of_the_money(self):
        """Current price well below threshold -> low probability."""
        fv = compute_crypto_fair_value(
            current_price=80000,
            threshold_price=88000,
            days_to_resolution=3.0,
            annual_volatility=0.60,
        )
        assert fv < 0.35

    def test_longer_time_higher_uncertainty(self):
        """More time -> probability closer to 0.50 (more uncertainty)."""
        fv_short = compute_crypto_fair_value(
            current_price=85000,
            threshold_price=88000,
            days_to_resolution=1.0,
            annual_volatility=0.60,
        )
        fv_long = compute_crypto_fair_value(
            current_price=85000,
            threshold_price=88000,
            days_to_resolution=14.0,
            annual_volatility=0.60,
        )
        # Both below 0.50, but longer time should be closer to 0.50
        assert fv_long > fv_short

    def test_higher_vol_higher_uncertainty(self):
        """Higher vol -> probability closer to 0.50."""
        fv_low = compute_crypto_fair_value(
            current_price=85000,
            threshold_price=88000,
            days_to_resolution=3.0,
            annual_volatility=0.30,
        )
        fv_high = compute_crypto_fair_value(
            current_price=85000,
            threshold_price=88000,
            days_to_resolution=3.0,
            annual_volatility=0.90,
        )
        assert fv_high > fv_low

    def test_zero_time_binary(self):
        """At resolution time: above threshold -> 1, below -> 0."""
        fv_above = compute_crypto_fair_value(
            current_price=90000,
            threshold_price=88000,
            days_to_resolution=0.001,
            annual_volatility=0.60,
        )
        fv_below = compute_crypto_fair_value(
            current_price=85000,
            threshold_price=88000,
            days_to_resolution=0.001,
            annual_volatility=0.60,
        )
        assert fv_above > 0.95
        assert fv_below < 0.05


class TestDetectMispricing:
    def _config(self, min_dev=0.08) -> MispricingConfig:
        return MispricingConfig(
            enabled=True,
            crypto=CryptoMispricingConfig(min_deviation_pct=min_dev),
            multi_outcome=MultiOutcomeConfig(enabled=True, max_sum_deviation=0.10),
        )

    def test_no_mispricing_when_disabled(self):
        m = make_market()
        config = MispricingConfig(enabled=False)
        result = detect_mispricing(m, config)
        assert result.signal == "none"

    def test_no_mispricing_for_non_crypto(self):
        m = make_market(market_type="political")
        result = detect_mispricing(m, self._config())
        assert result.signal == "none"
        assert result.theoretical_fair_value is None

    def test_mispricing_detected_crypto(self):
        """When market overprices YES vs model, signal should be non-none."""
        m = make_market(
            market_type="crypto_threshold",
            title="Will BTC be above $88,000 on March 30?",
            yes_price=0.70,  # market says 70%
        )
        # If model says ~50%, deviation is 20% -> strong signal
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000,
            threshold_price=88000,
            annual_volatility=0.60,
            vol_source="30d_binance",
            vol_data_days=30,
        )
        assert result.signal in ("moderate", "strong")
        assert result.theoretical_fair_value is not None
        assert abs(result.theoretical_fair_value - 0.50) < 0.10

    def test_no_mispricing_when_deviation_small(self):
        """When market price is close to model, signal should be none/weak."""
        m = make_market(
            market_type="crypto_threshold",
            yes_price=0.52,
        )
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000,
            threshold_price=88000,
            annual_volatility=0.60,
            vol_source="30d_binance",
            vol_data_days=30,
        )
        # Model ~0.50, market 0.52, deviation ~2% < 8% threshold
        assert result.signal in ("none", "weak")

    def test_multi_outcome_deviation(self):
        """When event outcome prices don't sum to ~1.0, flag it."""
        m = make_market(event_outcome_prices_sum=1.15)
        result = detect_mispricing(m, self._config())
        assert result.multi_outcome_flag is True

    def test_multi_outcome_ok(self):
        m = make_market(event_outcome_prices_sum=1.03)
        result = detect_mispricing(m, self._config())
        assert result.multi_outcome_flag is False

    def test_low_confidence_kills_signal(self):
        """When vol is fallback or time is short, confidence=low → signal forced to none."""
        m = make_market(
            market_type="crypto_threshold",
            yes_price=0.70,
        )
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000,
            threshold_price=88000,
            annual_volatility=0.60,
            vol_source="fallback_default",  # fallback → low confidence
            vol_data_days=0,
        )
        assert result.model_confidence == "low"
        assert result.signal == "none"  # killed, not downgraded

    def test_direction_set_when_confident(self):
        m = make_market(
            market_type="crypto_threshold", yes_price=0.70,
            resolution_time=datetime(2026, 4, 5, tzinfo=UTC),
        )
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000, threshold_price=88000, annual_volatility=0.60,
            vol_source="30d_binance", vol_data_days=30,
        )
        assert result.direction == "overpriced"  # market 0.70 > model ~0.50

    def test_direction_none_when_low_confidence(self):
        m = make_market(market_type="crypto_threshold", yes_price=0.70)
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000, threshold_price=88000, annual_volatility=0.60,
            vol_source="fallback_default", vol_data_days=0,
        )
        assert result.direction is None  # low confidence → no direction

    def test_high_confidence_preserves_signal(self):
        m = make_market(
            market_type="crypto_threshold",
            yes_price=0.70,
            resolution_time=datetime(2026, 4, 5, tzinfo=UTC),  # 8 days out → high confidence
        )
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000,
            threshold_price=88000,
            annual_volatility=0.60,
            vol_source="30d_binance",
            vol_data_days=30,
        )
        assert result.model_confidence == "high"
        assert result.signal in ("moderate", "strong")

    def test_result_has_details(self):
        m = make_market(
            market_type="crypto_threshold",
            yes_price=0.70,
        )
        result = detect_mispricing(
            m, self._config(),
            current_underlying_price=88000,
            threshold_price=88000,
            annual_volatility=0.60,
            vol_source="30d_binance",
            vol_data_days=30,
        )
        assert result.details is not None
        assert len(result.details) > 0
