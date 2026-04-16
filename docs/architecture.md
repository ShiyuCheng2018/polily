# Architecture (v0.5.0)

## System Overview

```
User pastes Polymarket URL
        ↓
  Gamma API fetch → Score (5 dims) → Mispricing detect → AI narrative → Tier
        ↓                                                                  ↓
  events + markets persisted to SQLite               Tier A / B / C
        ↓
  Auto-monitor ON → Daemon poll loop (30s)
        ↓
  CLOB prices → Score refresh → Movement detection → AI trigger (if significant)
```

## Data Model (Unified SQLite)

All state in `data/polily.db`. No JSON files, no scan archives.

| Table | Role |
|-------|------|
| **events** | Parent entity — title, market_type, structure_score, tier, tags, neg_risk, closed |
| **markets** | Child of event — yes_price, bid/ask, spread, depth, book data, score_breakdown |
| **event_monitors** | Monitor state — auto_monitor flag, next_check_at, next_check_reason |
| **analyses** | Versioned AI analysis — trigger_source, narrative_output, mispricing_signal |
| **movement_log** | Per-tick movement records — magnitude, quality, label, snapshot |
| **paper_trades** | Simulated positions — entry/exit price, P&L, friction |
| **scan_logs** | Audit trail — scan type, status, counts, errors |
| **notifications** | Event alerts with read state |

**Key relationships**: events ← markets (1:N), events ← event_monitors (1:1), events ← analyses (1:N), movement_log references event_id + market_id (NULL for event-level).

## Single-Event Ingestion Pipeline

`scanner/scan/pipeline.py` — `fetch_and_score_event(slug)`

1. **Fetch** — Gamma API by slug → parse event + sub-markets
2. **Enrich orderbook** — `fetch_clob_market_data()` per market (4 CLOB endpoints, sem=100)
3. **Fetch underlying** — Binance tickers for crypto markets (deduped by asset)
4. **Score** — `compute_structure_score()` per market (5 dimensions + net_edge)
5. **Event score** — `compute_event_quality_score()` across sub-markets
6. **Persist** — upsert events, markets, scores, breakdowns to DB

## Structure Score (5 Dimensions)

Measures **tradability**, not profitability. Weights are type-specific (all sum to 100):

| Dimension | Default | Crypto | Sports | Political | What it measures |
|-----------|---------|--------|--------|-----------|-----------------|
| Liquidity Structure | 30 | 22 | 30 | 30 | Spread (40%) + log-scale depth (35%) + bid/ask balance (25%) |
| Objective Verifiability | 10 | 10 | 10 | 10 | Resolution type (0-50) + source quality (0-50), vague language penalty |
| Probability Space | 20 | 15 | 20 | 20 | Symmetric room min(p, 1-p), linear 0.10 → 0.50 |
| Time Structure | 25 | 18 | 25 | 25 | Sweet spot [1,5] days (70%) + catalyst proximity (30%) |
| Trading Friction | 15 | 10 | 15 | 15 | 6-tier inverse: <2% → 1.0, >8% → 0.0 |
| Net Edge | 0 | **25** | 0 | 0 | \|deviation%\| - round_trip_friction (crypto only) |

## Mispricing Detection

`scanner/scan/mispricing.py` — crypto markets only, requires Binance underlying price.

| Model | Formula | Markets |
|-------|---------|---------|
| European (threshold) | P(S_T > K) = N(d2), log-normal | "above"/"below"/"over"/"under" keywords |
| Barrier (first-passage) | P(touch K) = 2N(-\|ln(S/K)\| / (sigma * sqrt(T))) | "dip to"/"reach"/"hit" keywords |

Output: signal (none/weak/moderate/strong), direction (overpriced/underpriced), deviation_pct, fair_value + confidence band.

## Daemon Architecture

`scanner/daemon/scheduler.py` — APScheduler with dual executors.

```
┌─────────────────────────────────────────────┐
│              WatchScheduler                  │
│                                              │
│  poll executor (1 thread)                    │
│    └─ global_poll  every 30s                 │
│                                              │
│  ai executor (5 threads)                     │
│    ├─ movement-triggered analysis            │
│    └─ scheduled check (next_check_at)        │
│                                              │
│  Signals:                                    │
│    SIGTERM → graceful shutdown               │
│    SIGUSR1 → reload check jobs from DB       │
│                                              │
│  Lifecycle: launchd (macOS)                  │
│    PID → data/scheduler.pid                  │
│    Log → data/poll.log                       │
└─────────────────────────────────────────────┘
```

## Global Poll (30s Tick)

`scanner/daemon/poll_job.py` — `global_poll(db)`

Each tick executes 3 steps sequentially:

**Step 1 — CLOB Price Fetch**
- Fetches all monitored markets (event_monitors.auto_monitor=1, market not closed, has token)
- 4 endpoints per market via `scanner/core/clob.py`: /book + /midpoint + /price BUY + /price SELL
- 404 → mark market closed; all sub-markets closed → close event
- Fetches recent trades from Data API (batch, sem=5)
- Fetches Binance tickers for crypto symbols (deduped)

**Step 2 — Score Refresh** (`scanner/daemon/score_refresh.py`)
- Recalculates price-sensitive dimensions: liquidity, probability, friction, net_edge, mispricing
- Preserves stable dimensions: verifiability, time
- Refreshes event-level scores

**Step 3 — Movement Detection** (signal computation + AI trigger)
- Per sub-market: compute 5 raw signals → magnitude (0-100) + quality (0-100) → label
- Cold start guard: < 5 history entries → forced noise
- negRisk events get event-level metrics (overround, entropy, leader, TV distance, HHI, dutch_book_gap)
- Trigger check: max(M) >= 70 AND max(Q) >= 60 AND cooldown OK AND daily limit OK → submit to ai executor

## Movement Detection (Dual Dimensions)

`scanner/monitor/signals.py` + `scanner/monitor/scorer.py`

**Raw signals per market**: price_z_score, volume_ratio, book_imbalance, trade_concentration, volume_price_confirmation.

| | Magnitude >= 50 | Magnitude < 50 |
|---|---|---|
| **Quality >= 50** | **consensus** (broad agreement) | **slow_build** (gradual info digestion) |
| **Quality < 50** | **whale_move** (single big trade) | **noise** (random) |

**Trigger thresholds**: M >= 70 AND Q >= 60.
**Cooldown**: M >= 90 → 20min, M >= 80 → 30min, default → 60min.

## CLOB Data Fetch

`scanner/core/clob.py` — `fetch_clob_market_data(client, token_id)` — single source of truth for both poll and scan paths.

| Data needed | Endpoint | Degradation |
|-------------|----------|-------------|
| yes_price | /midpoint | None (yes_price = None) |
| best_bid | /price?side=BUY | None (bid/ask/spread = None) |
| best_ask | /price?side=SELL | None |
| book depth | /book | Raise (caller handles 404 etc.) |

Why /price not /book for bid/ask: negRisk markets' /book returns raw token orderbook (bid=0.01, ask=0.99), not real prices. /price aggregates complement matching liquidity.

## AI Agent

`scanner/agents/narrative_writer.py` — single autonomous agent.

- Invoked via `claude -p --allowedTools Read,Bash,Grep,WebSearch,TodoWrite,StructuredOutput`
- Reads polily.db autonomously, searches web for news/context
- Outputs: mode (discovery/position_management), summary, risk_flags, operations, next_check_at
- Structured output via JSON schema + --output-format json
- Fallback on CLI failure; 1 retry on incomplete output
- Heartbeat monitoring emits status every 5s

AI is optional. Disable with `ai.enabled: false` in config.

## TUI

Built with [Textual](https://textual.textualize.io/). Single screen + sidebar navigation.

| View | Role |
|------|------|
| Scan Log | URL input + scan history with step logs |
| Monitor List | Auto-monitored events, movement status, analysis history |
| Paper Status | Open/closed positions, P&L |
| History | Past analyses |
| Notifications | Event alerts |

- Worker threads for async scan/analysis (no UI blocking)
- Auto-refresh current view when daemon is alive
- Detail views: score breakdown, AI analysis versions, trade dialog with real-time CLOB pricing
- Auto-starts daemon on launch if monitored events exist
