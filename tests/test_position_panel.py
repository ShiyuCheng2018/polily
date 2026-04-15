"""Tests for PositionPanel price bar logic."""

from scanner.tui.components.position_panel import _price_bar


class TestPriceBar:
    def test_profitable_shows_green(self):
        bar = _price_bar(entry=0.25, current=0.30)
        assert "[green]" in bar

    def test_losing_shows_red(self):
        bar = _price_bar(entry=0.25, current=0.20)
        assert "[red]" in bar

    def test_at_entry_no_fill(self):
        bar = _price_bar(entry=0.25, current=0.25)
        # At entry price, fill should be at the entry marker
        assert "│" in bar

    def test_zero_entry(self):
        bar = _price_bar(entry=0, current=0.5)
        assert "░" in bar

    def test_bar_length(self):
        bar = _price_bar(entry=0.25, current=0.30, width=10)
        # Count actual display chars (strip Rich tags)
        import re
        clean = re.sub(r'\[.*?\]', '', bar)
        assert len(clean) == 10
