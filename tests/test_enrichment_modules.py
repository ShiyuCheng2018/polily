"""Tests for data enrichment module registry and crypto_threshold module."""

import pytest

from polily.market_types.protocol import DataEnrichmentModule
from polily.market_types.registry import discover_modules, find_matching_module, reset_registry
from tests.conftest import make_market


@pytest.fixture(autouse=True)
def clean_registry():
    reset_registry()
    yield
    reset_registry()


class TestDiscoverModules:
    def test_discovers_crypto_threshold(self):
        modules = discover_modules()
        assert "crypto_threshold" in modules

    def test_module_satisfies_protocol(self):
        modules = discover_modules()
        for _name, mod in modules.items():
            assert isinstance(mod, DataEnrichmentModule)

    def test_caches_result(self):
        m1 = discover_modules()
        m2 = discover_modules()
        assert m1 is m2


class TestFindMatchingModule:
    def test_matches_btc_threshold_market(self):
        m = make_market(title="Will the price of Bitcoin be above $66,000 on March 30?")
        mod = find_matching_module(m)
        assert mod is not None
        assert mod.name == "crypto_threshold"

    def test_no_match_for_political(self):
        m = make_market(title="Will the next President be a Democrat?")
        mod = find_matching_module(m)
        assert mod is None

    def test_no_match_for_sports(self):
        m = make_market(title="Lakers vs. Celtics")
        mod = find_matching_module(m)
        assert mod is None

    def test_matches_eth_threshold(self):
        m = make_market(title="Will Ethereum be above $2,000 on April 3?")
        mod = find_matching_module(m)
        assert mod is not None
