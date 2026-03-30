"""Market type modules.

Each .py file in this package (except protocol.py and registry.py)
is auto-discovered as a market type module.

To create a new market type module:
1. Create scanner/market_types/<name>.py
2. Implement a class with `name` and `classify()`,
   optionally `fetch_price_params()` and `detect_mispricing()`
3. Expose as: module = YourType()
4. Add keywords + scoring_overrides in config.yaml under market_types.<name>
"""

from scanner.market_types.registry import discover_modules, get_module

__all__ = ["discover_modules", "get_module"]
