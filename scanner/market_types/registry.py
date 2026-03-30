"""Module registry: auto-discover and load market type modules."""

import importlib
import logging
import pkgutil
from pathlib import Path

from scanner.market_types.protocol import MarketTypeModule

logger = logging.getLogger(__name__)

_SKIP_MODULES = {"protocol", "registry", "__init__"}
_registry: dict[str, MarketTypeModule] = {}
_loaded = False


def discover_modules() -> dict[str, MarketTypeModule]:
    """Scan scanner/market_types/ for market type modules. Cached after first call."""
    global _registry, _loaded
    if _loaded:
        return _registry

    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name in _SKIP_MODULES:
            continue
        try:
            mod = importlib.import_module(f"scanner.market_types.{module_info.name}")
            module = getattr(mod, "module", None)
            if module is None:
                logger.debug("Skipped %s: no 'module' variable", module_info.name)
                continue
            if not isinstance(module, MarketTypeModule):
                logger.warning(
                    "Skipped %s: does not implement MarketTypeModule (need name + classify)",
                    module_info.name,
                )
                continue
            if module.name in _registry:
                logger.warning(
                    "Duplicate market type module name '%s' in %s, keeping first",
                    module.name, module_info.name,
                )
                continue
            _registry[module.name] = module
            logger.debug("Loaded market type module: %s", module.name)
        except Exception:
            logger.exception("Failed to load market type module: %s", module_info.name)

    _loaded = True
    return _registry


def get_module(name: str) -> MarketTypeModule | None:
    """Get a loaded market type module by name."""
    if not _loaded:
        discover_modules()
    return _registry.get(name)


def reset_registry():
    """Clear registry (for testing)."""
    global _registry, _loaded
    _registry = {}
    _loaded = False
