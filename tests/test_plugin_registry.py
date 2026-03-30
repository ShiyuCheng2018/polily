"""Tests for market type module registry."""


import pytest

from scanner.market_types.protocol import MarketTypeModule
from scanner.market_types.registry import discover_modules, get_module, reset_registry


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    reset_registry()
    yield
    reset_registry()


class TestDiscoverModules:
    def test_discovers_crypto_threshold_module(self):
        modules = discover_modules()
        assert "crypto_threshold" in modules

    def test_module_satisfies_protocol(self):
        modules = discover_modules()
        for _name, module in modules.items():
            assert isinstance(module, MarketTypeModule)
            assert hasattr(module, "name")
            assert hasattr(module, "classify")

    def test_skips_protocol_and_registry_modules(self):
        modules = discover_modules()
        assert "protocol" not in modules
        assert "registry" not in modules

    def test_caches_result(self):
        m1 = discover_modules()
        m2 = discover_modules()
        assert m1 is m2

    def test_reset_clears_cache(self):
        m1 = discover_modules()
        reset_registry()
        m2 = discover_modules()
        assert m1 is not m2


class TestGetModule:
    def test_get_existing(self):
        module = get_module("crypto_threshold")
        assert module is not None
        assert module.name == "crypto_threshold"

    def test_get_nonexistent(self):
        assert get_module("nonexistent_type") is None


class TestModuleInterface:
    def test_classify_returns_float(self):
        from tests.conftest import make_market
        module = get_module("crypto_threshold")
        assert module is not None
        m = make_market(title="Will Bitcoin be above $100,000 by June 30?")
        score = module.classify(m, ["bitcoin", "btc", "crypto"])
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_classify_high_confidence_for_crypto(self):
        from tests.conftest import make_market
        module = get_module("crypto_threshold")
        m = make_market(title="Will the price of Bitcoin be above $66,000 on March 30?")
        score = module.classify(m, ["bitcoin", "btc", "price"])
        assert score > 0.7

    def test_classify_low_for_non_crypto(self):
        from tests.conftest import make_market
        module = get_module("crypto_threshold")
        m = make_market(title="Will the next President be a Democrat?")
        score = module.classify(m, ["bitcoin", "btc"])
        assert score < 0.3

    def test_has_fetch_price_params(self):
        module = get_module("crypto_threshold")
        assert hasattr(module, "fetch_price_params")

    def test_has_detect_mispricing(self):
        module = get_module("crypto_threshold")
        assert hasattr(module, "detect_mispricing")
