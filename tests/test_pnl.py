"""Tests for P&L calculation pure functions."""

from scanner.pnl import calc_unrealized_pnl


class TestCalcUnrealizedPnl:
    def test_yes_side_profit(self):
        """YES: entry 0.50, current 0.60, size $20 → profit."""
        result = calc_unrealized_pnl("yes", 0.50, 0.60, 20.0)
        assert result["shares"] == 40.0
        assert result["pnl"] == 4.0  # (0.60 - 0.50) * 40
        assert result["pnl_pct"] == 20.0
        assert result["current_value"] == 24.0

    def test_yes_side_loss(self):
        """YES: entry 0.60, current 0.40 → loss."""
        result = calc_unrealized_pnl("yes", 0.60, 0.40, 20.0)
        assert result["pnl"] < 0
        assert result["pnl_pct"] < 0

    def test_no_side_profit(self):
        """NO: entry 0.40 (NO price), current YES=0.50 → NO cur=0.50, profit."""
        result = calc_unrealized_pnl("no", 0.40, 0.50, 20.0)
        # NO current = 1 - 0.50 = 0.50, shares = 20/0.40 = 50
        assert result["shares"] == 50.0
        assert result["pnl"] == 5.0  # (0.50 - 0.40) * 50
        assert result["pnl_pct"] == 25.0

    def test_no_side_loss(self):
        """NO: entry 0.30, current YES=0.50 → NO cur=0.50, but entry was 0.30."""
        # Wait, if entry_price=0.30 for NO, and YES goes to 0.80, NO=0.20
        result = calc_unrealized_pnl("no", 0.30, 0.80, 20.0)
        # NO current = 1 - 0.80 = 0.20, shares = 20/0.30 = 66.7
        # value = 0.20 * 66.7 = 13.3, pnl = 13.3 - 20 = -6.7
        assert result["pnl"] < 0

    def test_break_even(self):
        """Entry = current → P&L = 0."""
        result = calc_unrealized_pnl("yes", 0.50, 0.50, 20.0)
        assert result["pnl"] == 0
        assert result["pnl_pct"] == 0

    def test_zero_entry_price(self):
        """Zero entry → no division error, returns zeros."""
        result = calc_unrealized_pnl("yes", 0.0, 0.50, 20.0)
        assert result["shares"] == 0
        assert result["pnl"] == 0
        assert result["pnl_pct"] == 0

    def test_zero_position_size(self):
        result = calc_unrealized_pnl("yes", 0.50, 0.60, 0.0)
        assert result["shares"] == 0
        assert result["pnl"] == 0
