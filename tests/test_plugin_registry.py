"""Tests for market type plugin registry."""


import pytest

from scanner.market_types.protocol import MarketTypePlugin
from scanner.market_types.registry import discover_plugins, get_plugin, reset_registry


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset registry between tests."""
    reset_registry()
    yield
    reset_registry()


class TestDiscoverPlugins:
    def test_discovers_crypto_threshold_plugin(self):
        plugins = discover_plugins()
        assert "crypto_threshold" in plugins

    def test_plugin_satisfies_protocol(self):
        plugins = discover_plugins()
        for _name, plugin in plugins.items():
            assert isinstance(plugin, MarketTypePlugin)
            assert hasattr(plugin, "name")
            assert hasattr(plugin, "classify")

    def test_skips_protocol_and_registry_modules(self):
        plugins = discover_plugins()
        assert "protocol" not in plugins
        assert "registry" not in plugins

    def test_caches_result(self):
        p1 = discover_plugins()
        p2 = discover_plugins()
        assert p1 is p2

    def test_reset_clears_cache(self):
        p1 = discover_plugins()
        reset_registry()
        p2 = discover_plugins()
        assert p1 is not p2


class TestGetPlugin:
    def test_get_existing(self):
        plugin = get_plugin("crypto_threshold")
        assert plugin is not None
        assert plugin.name == "crypto_threshold"

    def test_get_nonexistent(self):
        assert get_plugin("nonexistent_type") is None


class TestPluginInterface:
    def test_classify_returns_float(self):
        from tests.conftest import make_market
        plugin = get_plugin("crypto_threshold")
        assert plugin is not None
        m = make_market(title="Will Bitcoin be above $100,000 by June 30?")
        score = plugin.classify(m, ["bitcoin", "btc", "crypto"])
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_classify_high_confidence_for_crypto(self):
        from tests.conftest import make_market
        plugin = get_plugin("crypto_threshold")
        m = make_market(title="Will the price of Bitcoin be above $66,000 on March 30?")
        score = plugin.classify(m, ["bitcoin", "btc", "price"])
        assert score > 0.7

    def test_classify_low_for_non_crypto(self):
        from tests.conftest import make_market
        plugin = get_plugin("crypto_threshold")
        m = make_market(title="Will the next President be a Democrat?")
        score = plugin.classify(m, ["bitcoin", "btc"])
        assert score < 0.3

    def test_has_fetch_price_params(self):
        plugin = get_plugin("crypto_threshold")
        assert hasattr(plugin, "fetch_price_params")

    def test_has_detect_mispricing(self):
        plugin = get_plugin("crypto_threshold")
        assert hasattr(plugin, "detect_mispricing")
