"""Tests for event-level metrics computation."""
from polily.monitor.event_metrics import compute_event_metrics


class TestOverround:
    def test_fair_market(self):
        prices = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        metrics = compute_event_metrics(prices)
        assert abs(metrics.overround - 0.0) < 0.001

    def test_overround_positive(self):
        prices = {"m1": 0.5, "m2": 0.3, "m3": 0.25}
        metrics = compute_event_metrics(prices)
        assert abs(metrics.overround - 0.05) < 0.001


class TestEntropy:
    def test_uniform_max_entropy(self):
        prices = {"m1": 0.25, "m2": 0.25, "m3": 0.25, "m4": 0.25}
        metrics = compute_event_metrics(prices)
        assert abs(metrics.entropy - 1.0) < 0.01  # normalized to 1.0

    def test_concentrated_low_entropy(self):
        prices = {"m1": 0.95, "m2": 0.02, "m3": 0.03}
        metrics = compute_event_metrics(prices)
        assert metrics.entropy < 0.5

    def test_two_outcomes_even(self):
        prices = {"m1": 0.5, "m2": 0.5}
        metrics = compute_event_metrics(prices)
        assert abs(metrics.entropy - 1.0) < 0.01

    def test_single_outcome(self):
        """Single market → entropy = 0 (no uncertainty)."""
        prices = {"m1": 1.0}
        metrics = compute_event_metrics(prices)
        assert metrics.entropy == 0.0


class TestLeader:
    def test_leader_identification(self):
        prices = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        metrics = compute_event_metrics(prices)
        assert metrics.leader_id == "m1"
        assert abs(metrics.leader_margin - 0.2) < 0.001  # 0.5 - 0.3

    def test_leader_changed(self):
        prev = {"m1": 0.4, "m2": 0.3, "m3": 0.3}
        curr = {"m1": 0.25, "m2": 0.45, "m3": 0.3}
        metrics = compute_event_metrics(curr, prev_prices=prev)
        assert metrics.leader_changed is True
        assert metrics.leader_id == "m2"

    def test_leader_not_changed(self):
        prev = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        curr = {"m1": 0.45, "m2": 0.35, "m3": 0.2}
        metrics = compute_event_metrics(curr, prev_prices=prev)
        assert metrics.leader_changed is False

    def test_no_prev_prices(self):
        prices = {"m1": 0.5, "m2": 0.3}
        metrics = compute_event_metrics(prices)
        assert metrics.leader_changed is False  # can't detect without prev


class TestTVDistance:
    def test_no_change(self):
        prev = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        curr = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        metrics = compute_event_metrics(curr, prev_prices=prev)
        assert abs(metrics.tv_distance) < 0.001

    def test_shift(self):
        prev = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        curr = {"m1": 0.4, "m2": 0.4, "m3": 0.2}
        metrics = compute_event_metrics(curr, prev_prices=prev)
        # TV = 0.5 * (|0.1| + |0.1| + 0) = 0.1
        assert abs(metrics.tv_distance - 0.1) < 0.001

    def test_no_prev(self):
        prices = {"m1": 0.5, "m2": 0.3}
        metrics = compute_event_metrics(prices)
        assert metrics.tv_distance == 0.0


class TestHHI:
    def test_concentrated(self):
        prices = {"m1": 0.9, "m2": 0.1}
        metrics = compute_event_metrics(prices)
        # HHI = 0.81 + 0.01 = 0.82
        assert abs(metrics.hhi - 0.82) < 0.001

    def test_uniform(self):
        prices = {"m1": 0.25, "m2": 0.25, "m3": 0.25, "m4": 0.25}
        metrics = compute_event_metrics(prices)
        # HHI = 4 * 0.0625 = 0.25
        assert abs(metrics.hhi - 0.25) < 0.001


class TestDutchBook:
    def test_no_asks_returns_zero(self):
        prices = {"m1": 0.5, "m2": 0.3}
        metrics = compute_event_metrics(prices)
        assert metrics.dutch_book_gap == 0.0

    def test_arb_opportunity(self):
        prices = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        asks = {"m1": 0.52, "m2": 0.32, "m3": 0.13}
        metrics = compute_event_metrics(prices, asks=asks)
        # gap = 1 - (0.52 + 0.32 + 0.13) = 1 - 0.97 = 0.03
        assert abs(metrics.dutch_book_gap - 0.03) < 0.001

    def test_no_arb(self):
        prices = {"m1": 0.5, "m2": 0.3, "m3": 0.2}
        asks = {"m1": 0.55, "m2": 0.35, "m3": 0.25}
        metrics = compute_event_metrics(prices, asks=asks)
        # gap = 1 - 1.15 = -0.15 (negative = no arb)
        assert metrics.dutch_book_gap < 0
