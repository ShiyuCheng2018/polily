"""Tests for paper trade auto-resolve via Polymarket API.

TODO: v0.5.0 — rewrite when auto_resolve is updated to use paper_store.
"""


from scanner.auto_resolve import _determine_result


class TestDetermineResult:
    def test_yes_won(self):
        market = {"resolved": True, "closed": True, "outcomePrices": '["1.00", "0.00"]'}
        assert _determine_result(market) == "yes"

    def test_no_won(self):
        market = {"resolved": True, "closed": True, "outcomePrices": '["0.00", "1.00"]'}
        assert _determine_result(market) == "no"

    def test_not_resolved(self):
        market = {"resolved": False, "closed": False}
        assert _determine_result(market) is None

    def test_ambiguous_prices(self):
        market = {"resolved": True, "outcomePrices": '["0.50", "0.50"]'}
        assert _determine_result(market) is None
