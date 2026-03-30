# Market Type Plugin Guide

Add new market types to Polily without modifying core code.

## Quick Start

```bash
# Scaffold a new plugin
polily new-plugin weather

# Edit the generated files
# scanner/market_types/weather.py  — plugin logic
# tests/test_plugin_weather.py     — tests

# Add keywords to config
# config.example.yaml → market_types.weather

# Verify
polily plugins          # check it loaded
pytest tests/test_plugin_weather.py
```

## Plugin Structure

A plugin is a Python file in `scanner/market_types/` that exposes a `plugin` variable:

```python
# scanner/market_types/weather.py

from scanner.utils import count_matches

class WeatherPlugin:
    name = "weather"  # must match config.yaml key

    def classify(self, market, keywords):
        """Return 0.0-1.0 confidence. Required."""
        return min(1.0, count_matches(market.title, keywords) / 2.0)

plugin = WeatherPlugin()
```

That's it. No core code changes needed.

## Plugin Methods

### `classify(market, keywords) -> float` (required)

Determine if a market belongs to this type.

- `market`: a `Market` object (see key fields below)
- `keywords`: list of strings from config.yaml
- Returns: 0.0 (definitely not) to 1.0 (definitely yes)
- When multiple plugins match, highest confidence wins

### `fetch_price_params(market, config) -> dict | None` (optional, async)

Fetch external price data for mispricing detection.

- Called once per market during scan pipeline
- Returns a dict of params passed to `detect_mispricing`
- Return `None` if no data available

### `detect_mispricing(market, price_params, config) -> MispricingResult | None` (optional, sync)

Custom mispricing detection using fetched price data.

- `price_params`: dict returned by `fetch_price_params`
- Returns `MispricingResult` or `None` to fall through to generic logic

## Market Model Key Fields

```python
market.title               # "Will Bitcoin be above $66,000 on March 30?"
market.description         # Full market description
market.market_type         # Assigned type (your plugin sets this)
market.tags                # ["crypto", "bitcoin"]
market.outcomes            # ["Yes", "No"]
market.yes_price           # 0.64
market.no_price            # 0.36
market.volume              # 80000.0
market.days_to_resolution  # 4.3
market.resolution_source   # "https://..."
market.spread_pct_yes      # 0.029
```

## MispricingResult Fields

```python
MispricingResult(
    signal="moderate",              # "none", "weak", "moderate", "strong"
    direction="underpriced",        # "underpriced", "overpriced", None
    theoretical_fair_value=0.65,    # model's fair value
    deviation_pct=0.10,             # abs(market - fair) / fair
    details="Model 0.65, market 0.55",
    model_confidence="high",        # "high", "medium", "low"
)
```

## Config

Add your type to `config.example.yaml`:

```yaml
market_types:
  weather:
    keywords: ["temperature", "rainfall", "hurricane", "weather", "climate"]
    scoring_overrides:
      catalyst_proxy: 12  # weather events have clear catalysts
```

`scoring_overrides` adjusts Structure Score weights for this market type.

## Testing

Use `make_market()` from `tests/conftest.py`:

```python
from scanner.market_types.weather import plugin
from tests.conftest import make_market

def test_classify_weather():
    m = make_market(title="Will temperature exceed 100F in Phoenix by July?")
    assert plugin.classify(m, ["temperature", "weather"]) > 0.7

def test_classify_not_weather():
    m = make_market(title="Will Bitcoin hit $100k?")
    assert plugin.classify(m, ["temperature", "weather"]) < 0.1
```

## Example: Full Plugin with Price Feed

See `scanner/market_types/crypto_threshold.py` for a complete example with `classify`, `fetch_price_params`, and `detect_mispricing`.

## Checking Your Plugin

```bash
polily plugins    # verify it loaded
polily scan       # run a scan, check your type appears
```
