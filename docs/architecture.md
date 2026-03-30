# Architecture

## Pipeline

```
Polymarket API → Hard Filters → Market Classification → Structure Score → Mispricing Detection
     ↓                                                                         ↓
  8000+ markets                                                    Tier A (research) + Tier B (watchlist)
                                                                          ↓
                                                         AI Agents → Analysis + Risk Calculator → Output
```

## Data Flow

1. **Fetch**: Polymarket Gamma API → `Market` objects
2. **Filter**: 8 hard filter rules (volume, probability, noise, etc.)
3. **Classify**: keyword-based market type detection (crypto, political, sports, etc.)
4. **Score**: Structure Score (0-100) with 7 weighted components
5. **Mispricing**: Log-normal vol model for crypto markets via Binance/ccxt
6. **AI Analysis**: 5 agents via Claude CLI for semantic analysis and narratives
7. **Tier**: Classify into Research (>=75), Watchlist (>=60), Filtered (<60)

## Structure Score

Measures **market tradability**, not profitability. High score = worth investigating.

| Component | Weight | What it measures |
|-----------|--------|-----------------|
| Time to resolution | 15 | Prefer 0.5-7 days |
| Objectivity | 20 | Clear resolution criteria |
| Probability zone | 20 | Prefer 0.30-0.70 |
| Liquidity & depth | 20 | Tight spread + real book depth |
| Exitability | 10 | Bid-side depth for selling |
| Catalyst proxy | 5 | Event-driven structure |
| Small-account friendly | 10 | Low friction for $20 trades |

## AI Agents

5 agents enhance the pipeline via `claude -p` (Claude CLI, included in subscription):

| Agent | Model | Purpose | Fallback |
|-------|-------|---------|----------|
| MarketAnalyst | Haiku | Objectivity scoring, catalyst extraction | Keyword heuristics |
| NarrativeWriter | Sonnet | Analysis narrative, risk flags, research checklist | Template text |
| BriefingAnalyst | Sonnet | Daily delta interpretation | Numerical table |
| CrossDomainInsight | Sonnet | Event x market cross-domain analysis | Static mapping |
| ReviewAnalyst | Sonnet | Paper trading performance coaching | Statistics only |

AI is optional. Disable with `ai.enabled: false` in config or `--no-ai` flag.

## Storage

| Store | Format | Purpose |
|-------|--------|---------|
| `data/scans/*.json` | JSON files | Immutable scan snapshots, one per scan |
| `data/analyses.json` | JSON | Per-market AI analysis version history |
| `data/scan_logs.json` | JSON | Scan/analysis execution metadata |
| `data/paper_trades.db` | SQLite | Paper trade CRUD + aggregation |

## TUI Architecture

Built with [Textual](https://textual.textualize.io/). Single screen with sidebar navigation:

- **Scan Log**: Task history + live progress with braille spinner
- **Market List**: Sortable table with research/watchlist tiers
- **Market Detail**: Score breakdown, AI analysis with version history, risk calculator
- **Paper Status**: Open paper trade positions

Worker threads handle async scan/analysis without blocking UI. All UI updates go through `call_from_thread`.
