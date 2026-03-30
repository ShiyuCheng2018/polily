"""Tests for opinion matching: find markets matching a user's view."""



from scanner.match import find_matching_markets
from tests.conftest import make_market


class TestFindMatchingMarkets:
    def test_match_btc_view(self):
        markets = [
            make_market(market_id="m1", title="Will BTC be above $70,000 on April 5?", yes_price=0.45),
            make_market(market_id="m2", title="Will CPI exceed 3.5%?", yes_price=0.55),
            make_market(market_id="m3", title="BTC above $90,000 by May?", yes_price=0.20),
        ]
        results = find_matching_markets("BTC will hit 70k", markets)
        assert len(results) >= 1
        assert results[0].market.market_id == "m1"  # best match

    def test_match_fed_view(self):
        markets = [
            make_market(market_id="m1", title="Will Fed cut rates in June?", yes_price=0.40),
            make_market(market_id="m2", title="BTC above 88K?", yes_price=0.50),
        ]
        results = find_matching_markets("Fed will cut rates", markets)
        assert len(results) >= 1
        assert results[0].market.market_id == "m1"

    def test_no_match(self):
        markets = [
            make_market(market_id="m1", title="Lakers win championship?", yes_price=0.50),
        ]
        results = find_matching_markets("Ethereum merge", markets)
        assert len(results) == 0

    def test_result_has_payoff(self):
        markets = [
            make_market(market_id="m1", title="BTC above $70,000?", yes_price=0.45),
        ]
        results = find_matching_markets("BTC will be above 70k", markets)
        assert results[0].payoff_if_right > 0
        assert results[0].payoff_if_right > results[0].cost

    def test_returns_multiple_matches(self):
        markets = [
            make_market(market_id="m1", title="BTC above $90,000 by December?", yes_price=0.15),
            make_market(market_id="m2", title="Will BTC be above $70,000 on April 5?", yes_price=0.45),
            make_market(market_id="m3", title="Will Lakers win?", yes_price=0.50),
        ]
        results = find_matching_markets("BTC above 70000", markets)
        ids = [r.market.market_id for r in results]
        assert "m1" in ids or "m2" in ids  # at least one BTC match
        assert "m3" not in ids  # Lakers doesn't match
