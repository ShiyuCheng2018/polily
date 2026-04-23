"""Data enrichment modules for market types.

Modules provide external data sources and custom mispricing detection
for specific market types. Classification is handled by tag_classifier.py
using Polymarket event tags — modules only enrich markets with external data.

To create a new module:
1. Create polily/market_types/<name>.py
2. Implement matches(), fetch_price_params(), detect_mispricing()
3. Expose as: module = YourModule()
"""

from polily.market_types.registry import discover_modules, get_module

__all__ = ["discover_modules", "get_module"]
