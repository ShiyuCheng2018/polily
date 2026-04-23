"""Module registry: auto-discover data enrichment modules."""

import importlib
import logging
import pkgutil
from pathlib import Path

from polily.market_types.protocol import DataEnrichmentModule

logger = logging.getLogger(__name__)

_SKIP = {"protocol", "registry", "__init__"}
_registry: dict[str, DataEnrichmentModule] = {}
_loaded = False


def discover_modules() -> dict[str, DataEnrichmentModule]:
    """Scan polily/market_types/ for data enrichment modules. Cached after first call."""
    global _registry, _loaded
    if _loaded:
        return _registry

    package_dir = Path(__file__).parent
    for module_info in pkgutil.iter_modules([str(package_dir)]):
        if module_info.name in _SKIP:
            continue
        try:
            mod = importlib.import_module(f"polily.market_types.{module_info.name}")
            enrichment = getattr(mod, "module", None)
            if enrichment is None:
                continue
            if not isinstance(enrichment, DataEnrichmentModule):
                logger.warning("Skipped %s: does not implement DataEnrichmentModule", module_info.name)
                continue
            _registry[enrichment.name] = enrichment
            logger.debug("Loaded data enrichment module: %s", enrichment.name)
        except Exception:
            logger.exception("Failed to load module: %s", module_info.name)

    _loaded = True
    return _registry


def get_module(name: str) -> DataEnrichmentModule | None:
    """Get a loaded module by name."""
    if not _loaded:
        discover_modules()
    return _registry.get(name)


def find_matching_module(market) -> DataEnrichmentModule | None:
    """Find a module that matches this market."""
    if not _loaded:
        discover_modules()
    for enrichment in _registry.values():
        if enrichment.matches(market):
            return enrichment
    return None


def reset_registry():
    """Clear registry (for testing)."""
    global _registry, _loaded
    _registry = {}
    _loaded = False
