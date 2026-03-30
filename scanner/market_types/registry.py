"""Plugin registry: auto-discover and load market type plugins."""

import importlib
import logging
import pkgutil
from pathlib import Path

from scanner.market_types.protocol import MarketTypePlugin

logger = logging.getLogger(__name__)

_SKIP_MODULES = {"protocol", "registry", "__init__"}
_registry: dict[str, MarketTypePlugin] = {}
_loaded = False


def discover_plugins() -> dict[str, MarketTypePlugin]:
    """Scan scanner/market_types/ for plugin modules. Cached after first call."""
    global _registry, _loaded
    if _loaded:
        return _registry

    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name in _SKIP_MODULES:
            continue
        try:
            mod = importlib.import_module(f"scanner.market_types.{module_info.name}")
            plugin = getattr(mod, "plugin", None)
            if plugin is None:
                logger.debug("Skipped %s: no 'plugin' variable", module_info.name)
                continue
            if not isinstance(plugin, MarketTypePlugin):
                logger.warning(
                    "Skipped %s: does not implement MarketTypePlugin (need name + classify)",
                    module_info.name,
                )
                continue
            if plugin.name in _registry:
                logger.warning(
                    "Duplicate plugin name '%s' in %s, keeping first",
                    plugin.name, module_info.name,
                )
                continue
            _registry[plugin.name] = plugin
            logger.debug("Loaded plugin: %s", plugin.name)
        except Exception:
            logger.exception("Failed to load plugin: %s", module_info.name)

    _loaded = True
    return _registry


def get_plugin(name: str) -> MarketTypePlugin | None:
    """Get a loaded plugin by name."""
    if not _loaded:
        discover_plugins()
    return _registry.get(name)


def reset_registry():
    """Clear registry (for testing)."""
    global _registry, _loaded
    _registry = {}
    _loaded = False
