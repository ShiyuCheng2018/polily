"""Tests for order book depth analysis."""

import pytest

from scanner.models import BookLevel
from scanner.orderbook import (
    OrderBookAnalysis,
    analyze_book,
    compute_depth_imbalance,
    compute_slippage,
    is_stale_book,
)


def _sample_bids():
    return [
        BookLevel(price=0.54, size=1500),
        BookLevel(price=0.53, size=2000),
        BookLevel(price=0.52, size=800),
    ]


def _sample_asks():
    return [
        BookLevel(price=0.56, size=1200),
        BookLevel(price=0.57, size=1800),
        BookLevel(price=0.58, size=500),
    ]


class TestComputeSlippage:
    def test_small_order_no_slippage(self):
        """$5 order against $1500 top level -> essentially no slippage."""
        asks = _sample_asks()
        avg_price, slippage_pct = compute_slippage(asks, order_size_usd=5.0)
        assert avg_price == pytest.approx(0.56, abs=0.001)
        assert slippage_pct < 0.01

    def test_order_eats_first_level(self):
        """$1200 order exactly consumes first ask level."""
        asks = _sample_asks()
        avg_price, slippage_pct = compute_slippage(asks, order_size_usd=1200.0)
        assert avg_price == pytest.approx(0.56, abs=0.001)

    def test_order_spans_levels(self):
        """$2000 order spans first two levels."""
        asks = _sample_asks()
        avg_price, slippage_pct = compute_slippage(asks, order_size_usd=2000.0)
        # $1200 at 0.56, $800 at 0.57 -> avg = (1200*0.56 + 800*0.57) / 2000
        assert avg_price > 0.56
        assert avg_price < 0.57

    def test_order_exceeds_book(self):
        """Order larger than total book depth."""
        asks = _sample_asks()  # total = 3500
        avg_price, slippage_pct = compute_slippage(asks, order_size_usd=5000.0)
        assert avg_price > 0.56
        assert slippage_pct > 0

    def test_empty_book(self):
        avg_price, slippage_pct = compute_slippage([], order_size_usd=20.0)
        assert avg_price is None
        assert slippage_pct is None

    def test_zero_order(self):
        avg_price, slippage_pct = compute_slippage(_sample_asks(), order_size_usd=0)
        assert slippage_pct == 0.0


class TestDepthImbalance:
    def test_balanced_book(self):
        bids = [BookLevel(price=0.50, size=1000)]
        asks = [BookLevel(price=0.52, size=1000)]
        ratio = compute_depth_imbalance(bids, asks)
        assert ratio == pytest.approx(1.0)

    def test_bid_heavy(self):
        bids = [BookLevel(price=0.50, size=3000)]
        asks = [BookLevel(price=0.52, size=1000)]
        ratio = compute_depth_imbalance(bids, asks)
        assert ratio == pytest.approx(3.0)

    def test_empty_asks(self):
        bids = [BookLevel(price=0.50, size=1000)]
        ratio = compute_depth_imbalance(bids, [])
        assert ratio is None


class TestIsStaleBook:
    def test_normal_book_not_stale(self):
        bids = _sample_bids()
        asks = _sample_asks()
        assert is_stale_book(bids, asks) is False

    def test_extreme_spread_is_stale(self):
        bids = [BookLevel(price=0.01, size=100)]
        asks = [BookLevel(price=0.99, size=100)]
        assert is_stale_book(bids, asks) is True

    def test_empty_book_is_stale(self):
        assert is_stale_book([], []) is True


class TestAnalyzeBook:
    def test_analyze_returns_complete_analysis(self):
        result = analyze_book(_sample_bids(), _sample_asks(), order_size_usd=20.0)
        assert isinstance(result, OrderBookAnalysis)
        assert result.total_bid_depth > 0
        assert result.total_ask_depth > 0
        assert result.slippage_pct is not None
        assert result.imbalance_ratio is not None
        assert result.is_stale is False

    def test_analyze_empty_book(self):
        result = analyze_book([], [], order_size_usd=20.0)
        assert result.is_stale is True
        assert result.total_bid_depth == 0
