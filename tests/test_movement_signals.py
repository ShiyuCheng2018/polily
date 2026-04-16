import pytest

from scanner.monitor.signals import (
    compute_book_imbalance,
    compute_cross_divergence,
    compute_fair_value_divergence,
    compute_open_interest_delta,
    compute_price_z_score,
    compute_sustained_drift,
    compute_time_decay_adjusted_move,
    compute_trade_concentration,
    compute_underlying_z_score,
    compute_volume_price_confirmation,
    compute_volume_ratio,
)

# --- Universal signals ---


class TestPriceZScore:
    def test_stable_prices_zero_z(self):
        prices = [0.50] * 20
        z = compute_price_z_score(0.50, prices)
        assert z == 0.0

    def test_big_move_high_z(self):
        prices = [0.50 + (i % 3) * 0.01 for i in range(20)]
        z = compute_price_z_score(0.70, prices)
        assert z > 2.0

    def test_insufficient_data(self):
        z = compute_price_z_score(0.50, [0.50])
        assert z == 0.0

    def test_zero_std_returns_zero(self):
        prices = [0.50, 0.50, 0.50]
        z = compute_price_z_score(0.51, prices)
        assert z == 0.0


class TestVolumeRatio:
    def test_baseline_match(self):
        ratio = compute_volume_ratio(100.0, 100.0)
        assert ratio == pytest.approx(1.0)

    def test_spike(self):
        ratio = compute_volume_ratio(500.0, 100.0)
        assert ratio == pytest.approx(5.0)

    def test_zero_baseline(self):
        ratio = compute_volume_ratio(100.0, 0.0)
        assert ratio == 0.0


class TestBookImbalance:
    def test_balanced(self):
        imb = compute_book_imbalance(1000.0, 1000.0)
        assert imb == pytest.approx(0.0)

    def test_bid_heavy(self):
        imb = compute_book_imbalance(3000.0, 1000.0)
        assert imb == pytest.approx(0.5)

    def test_ask_heavy(self):
        imb = compute_book_imbalance(1000.0, 3000.0)
        assert imb == pytest.approx(-0.5)

    def test_zero_depth(self):
        imb = compute_book_imbalance(0.0, 0.0)
        assert imb == 0.0


class TestTradeConcentration:
    def test_single_whale(self):
        trades_sizes = [900.0, 50.0, 50.0]
        tc = compute_trade_concentration(trades_sizes)
        assert tc == pytest.approx(0.9)

    def test_dispersed(self):
        trades_sizes = [100.0] * 10
        tc = compute_trade_concentration(trades_sizes)
        assert tc == pytest.approx(0.1)

    def test_empty(self):
        tc = compute_trade_concentration([])
        assert tc == 0.0


class TestOpenInterestDelta:
    def test_increase(self):
        delta = compute_open_interest_delta(110000.0, 100000.0)
        assert delta == pytest.approx(0.1)

    def test_decrease(self):
        delta = compute_open_interest_delta(90000.0, 100000.0)
        assert delta == pytest.approx(-0.1)

    def test_zero_previous(self):
        delta = compute_open_interest_delta(100.0, 0.0)
        assert delta == 0.0


# --- Market-type-specific signals ---


class TestFairValueDivergence:
    def test_no_divergence(self):
        d = compute_fair_value_divergence(0.60, 0.60)
        assert d == pytest.approx(0.0)

    def test_positive_divergence(self):
        d = compute_fair_value_divergence(0.50, 0.65)
        assert d == pytest.approx(0.15)

    def test_negative_divergence(self):
        d = compute_fair_value_divergence(0.70, 0.55)
        assert d == pytest.approx(0.15)


class TestUnderlyingZScore:
    def test_delegates_to_price_z(self):
        prices = [50000.0 + i * 100 for i in range(20)]
        z = compute_underlying_z_score(55000.0, prices)
        assert z > 2.0


class TestCrossDivergence:
    def test_both_move(self):
        d = compute_cross_divergence(0.05, 0.05)
        assert d == pytest.approx(0.0, abs=0.1)

    def test_underlying_moved_odds_didnt(self):
        d = compute_cross_divergence(0.05, 0.0)
        assert d > 0.5

    def test_zero_underlying(self):
        d = compute_cross_divergence(0.0, 0.05)
        assert d > 0.5


class TestSustainedDrift:
    def test_monotone_up(self):
        prices = [0.40, 0.42, 0.44, 0.46, 0.48, 0.50]
        drift = compute_sustained_drift(prices)
        assert drift > 0.5

    def test_oscillating(self):
        prices = [0.50, 0.52, 0.48, 0.51, 0.49, 0.50]
        drift = compute_sustained_drift(prices)
        assert drift < 0.7
        assert drift > 0.4

    def test_insufficient_data(self):
        drift = compute_sustained_drift([0.50])
        assert drift == 0.0


class TestTimedDecayAdjustedMove:
    def test_far_from_event(self):
        adj = compute_time_decay_adjusted_move(0.03, 30.0)
        assert adj < 0.5

    def test_close_to_event(self):
        adj = compute_time_decay_adjusted_move(0.03, 1.0)
        assert adj > 0.1


class TestVolumePriceConfirmation:
    def test_same_direction(self):
        vp = compute_volume_price_confirmation(0.05, 3.0)
        assert vp > 0.5

    def test_opposite_direction(self):
        vp = compute_volume_price_confirmation(0.05, 0.3)
        assert vp < 0.3

    def test_no_price_change(self):
        vp = compute_volume_price_confirmation(0.0, 3.0)
        assert vp == 0.0
