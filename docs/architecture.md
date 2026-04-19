# Architecture (v0.7.0+)

## System Overview

```
User pastes Polymarket URL
        ↓
  Gamma API fetch → Score (5 dims) → Mispricing detect → AI narrative → Tier
        ↓                                                                  ↓
  events + markets persisted to SQLite               Tier A / B / C
        ↓                                 ┌────────────────────────────────────┐
  Auto-monitor ON → Daemon (30s tick)     │  User opens TradeDialog            │
        ↓                                 │       ↓                            │
  CLOB fetch → Score refresh              │  TradeEngine (atomic BEGIN/COMMIT) │
        ↓                                 │       ├─ wallet.deduct (cash + fee)│
  Movement detect → AI (if significant)   │       ├─ positions.add_shares      │
        ↓                                 │       └─ wallet_transactions ledger│
  Auto-resolution (closed + UMA final)    └────────────────────────────────────┘
        ↓
  ResolutionHandler: wallet.credit + positions.delete + ledger RESOLVE row
```

## Data Model (Unified SQLite)

All state in `data/polily.db`. No JSON files, no scan archives.

| Table | Role |
|-------|------|
| **events** | Parent entity — title, market_type, structure_score, tier, tags, neg_risk, closed |
| **markets** | Child of event — yes_price, bid/ask, spread, depth, book data, score_breakdown |
| **event_monitors** | User-intent monitor state — auto_monitor flag, price_snapshot, notes (v0.7.0: scheduling moved to scan_logs) |
| **scan_logs** | Unified task ledger — manual / scheduled / movement AI analyses + URL scoring. Lifecycle: pending → running → completed/failed/cancelled/superseded. Dispatcher reads overdue `status='pending'` every 30s |
| **analyses** | Versioned AI analysis — trigger_source, narrative_output, mispricing_signal |
| **movement_log** | Per-tick movement records — magnitude, quality, label, snapshot |
| **positions** | Active exposure aggregated by (market_id, side) — weighted-avg cost, cost basis |
| **wallet** | Cash singleton — balance, starting_balance, topup/withdraw totals |
| **wallet_transactions** | Append-only ledger — BUY/SELL/FEE/RESOLVE/TOPUP/WITHDRAW with realized_pnl |

**Key relationships**: events ← markets (1:N), events ← event_monitors (1:1), events ← analyses (1:N), scan_logs.event_id references events (pending rows are the dispatcher's work queue), movement_log references event_id + market_id (NULL for event-level).

**Deprecated tables**: `notifications` was dropped in v0.6.1 (replaced by the Archive view + `events.closed`); `paper_trades` dropped in v0.6.1 (replaced by positions + wallet_transactions).

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

## Wallet System (v0.6.0+)

Paper-trading backed by a real ledger. Built around three tables with
atomicity guarantees so paper P&L reflects actual trading friction
rather than a hardcoded constant.

**Data flow**

```
execute_buy(shares)
    └─> BEGIN
        ├─ wallet.deduct(cost + fee)   → wallet_transactions(BUY)
        ├─ wallet.deduct(fee, commit=False) → wallet_transactions(FEE)  [if fees_enabled]
        └─ positions.add_shares(weighted-avg cost)
        COMMIT

execute_sell(shares)
    └─> BEGIN
        ├─ positions.remove_shares → realized_pnl
        ├─ wallet.credit(proceeds)      → wallet_transactions(SELL, realized_pnl)
        └─ wallet.deduct(fee)           → wallet_transactions(FEE)  [if fees_enabled]
        COMMIT

auto-resolution (poll tick, on closed market with UMA final)
    └─> BEGIN
        ├─ wallet.credit(payout × shares) → wallet_transactions(RESOLVE, realized_pnl)
        └─ positions.delete
        COMMIT
```

**Core tables**

- `wallet` — singleton row: cash_usd, starting_balance, topup_total, withdraw_total
- `positions` — one row per (market_id, side) with weighted-average avg_cost + cost_basis
- `wallet_transactions` — append-only ledger, types: BUY / SELL / FEE / RESOLVE / TOPUP / WITHDRAW

**Atomicity contract** (`scanner/core/trade_engine.py`): every public `execute_*` method
opens one `BEGIN` and calls inner writes with `commit=False`, so the cash delta, fee
deduction, and position mutation all commit together or all roll back. Same contract
for `ResolutionHandler.resolve_market` — the credit + position delete + ledger insert
are one transaction.

**Fees** (`scanner/core/fees.py`): quadratic Polymarket taker fee:
`fee = shares × rate × price × (1 − price)`. Rate comes from the market's
`feesEnabled` + `feeSchedule.rate` fields (per-market, not per-category).
Most Polymarket markets have `feesEnabled=false` → `fee = $0`.

**Auto-resolution** (`scanner/daemon/resolution.py`): a closed market with a live
position triggers a Gamma fetch. `derive_winner` gates on `umaResolutionStatuses`:

- `[]` — non-UMA market (price-feed settled) → honor `outcomePrices`
- `[…, "resolved"]` — UMA final → honor `outcomePrices`
- `["proposed"]` / `["disputed"]` / other — defer (next poll tick retries)

This prevents settling during the 2-hour UMA challenge window where `outcomePrices`
already shows the proposer's guess but can still flip.

**Realized-P&L history** (`HistoryView` + `ScanService.get_realized_history`): every
SELL and RESOLVE row in the ledger is one history entry. Fees are joined by
`(market_id, side, notes LIKE '%SELL%')` within a 2-second window so the per-sell
friction shown in the UI reflects the real fee amount, not an estimate.

## Daemon Architecture

`scanner/daemon/scheduler.py` — APScheduler with dual executors.

```
┌─────────────────────────────────────────────┐
│              WatchScheduler                  │
│                                              │
│  poll executor (1 thread)                    │
│    └─ global_poll  every 30s                 │
│         └─ Step 3.5: dispatcher drains       │
│            overdue scan_logs pending rows    │
│                                              │
│  ai executor (5 threads)                     │
│    └─ _run_pending_analysis                  │
│       (unified: scheduled/movement/manual)   │
│                                              │
│  Signals:                                    │
│    SIGTERM → graceful shutdown               │
│                                              │
│  Lifecycle: launchd (macOS)                  │
│    PID → data/scheduler.pid                  │
│    Log → data/logs/poll-v<ver>-<ts>.log      │
│          (per-restart rotation, old kept)    │
└─────────────────────────────────────────────┘
```

## Global Poll (30s Tick)

`scanner/daemon/poll_job.py` — `global_poll(db)`

Each tick executes these steps sequentially (numbering from the module docstring; Step 1.5 / 3.5 are later insertions that kept the original names):

**Step 1 — CLOB Price Fetch**
- Fetches all monitored markets (event_monitors.auto_monitor=1, market not closed, has token)
- 4 endpoints per market via `scanner/core/clob.py`: /book + /midpoint + /price BUY + /price SELL
- 404 → mark market closed; all sub-markets closed → close event
- Fetches recent trades from Data API (batch, sem=5)
- Fetches Binance tickers for crypto symbols (deduped)

**Step 1.5 — Auto-Resolution** (`scanner/daemon/resolution.py`)
- Runs immediately after the fetch so UMA status is as fresh as possible
- For each closed market where the user holds a live position: fetch Gamma to read
  `outcomePrices` + `umaResolutionStatuses`
- `derive_winner` gates on UMA status: proposed/disputed → defer; empty (non-UMA)
  or last-entry `"resolved"` → honor the price vector
- Settle atomically: `wallet.credit(payout × shares)` + `positions.delete` + ledger
  RESOLVE row, all in one `BEGIN/COMMIT`
- Zero Gamma calls for closed markets with no user exposure (read-through gate in
  `_has_positions`)

**Step 2 — Score Refresh** (`scanner/daemon/score_refresh.py`)
- Recalculates price-sensitive dimensions: liquidity, probability, friction, net_edge, mispricing
- Preserves stable dimensions: verifiability, time
- Refreshes event-level scores

**Step 3.5 — Pending Dispatcher** (v0.7.0, `dispatch_pending_analyses`)
- Scans `scan_logs` for overdue pending rows via `fetch_overdue_pending`
  (CTE picks earliest-per-event + `NOT EXISTS running` guard)
- Atomically claims each row (`claim_pending_scan` = UPDATE ... WHERE status='pending')
- Submits surviving rows to the `ai` executor via `_run_pending_analysis`, which
  constructs a fresh `ScanService` from `_ctx.config` and runs `analyze_event`
  with the claimed `scan_id`
- Per-row try/except so a single `add_job` failure doesn't abort the batch;
  failed claims get swept by `fail_orphan_running` on next daemon restart
- Runs BEFORE Step 3 movement detection so this-tick movement signals don't
  feed back into this-tick analyses (they land next tick)

**Step 3 — Movement Detection** (signal computation → pending-row write)
- Per sub-market: compute 5 raw signals → magnitude (0-100) + quality (0-100) → label
- Cold start guard: < 5 history entries → forced noise
- negRisk events get event-level metrics (overround, entropy, leader, TV distance, HHI, dutch_book_gap)
- Trigger check: max(M) >= 70 AND max(Q) >= 60 AND cooldown OK AND daily limit OK →
  `_trigger_movement_analysis` writes a `scan_logs` pending row with
  `trigger_source='movement'`, `scheduled_at=now`. The NEXT tick's Step 3.5
  dispatcher picks it up. All AI triggers (manual / scheduled / movement)
  share this one queue.

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
- Reads polily.db autonomously (events / markets / positions / wallet_transactions /
  analyses / movement_log), searches web for news/context
- Two modes driven by `_compute_position_context(event_id)`:
  - **discovery** — no positions on the event → evaluate whether it's worth entering,
    output BUY_YES / BUY_NO / PASS operations with position_size_usd, confidence,
    reasoning
  - **position_management** — user holds a live position → output HOLD /
    INCREASE / REDUCE / EXIT plus `thesis_status` (intact / weakened / invalidated),
    `thesis_note`, and optional `stop_loss` / `take_profit` trigger prices
- Common output fields: `summary`, `analysis`, `risk_flags` (severity-tagged),
  `research_findings` (source-cited), `time_window`, `next_check_at` +
  `next_check_reason`, `dev_feedback` (self-critique for product iteration)
- Structured output via JSON schema + `--output-format json`
- Fallback on CLI failure; 1 retry on incomplete output
- Heartbeat monitoring emits status every 5s

AI is optional. Disable with `ai.enabled: false` in config.

## TUI

Built with [Textual](https://textual.textualize.io/). Single screen + sidebar navigation.

| View | Role |
|------|------|
| 任务记录 (menu 0) | URL input + **分析队列** (pending/running) + **历史** (completed/failed/cancelled/superseded, with 类型 column for AI 分析 / 评分 / 扫描). `c` on a running row opens cancel-confirm modal. |
| Monitor List (menu 1) | Auto-monitored events — 结构分 / 子市场 / AI版 / 异动 / 结算 / 下次检查. `下次检查` column reads the earliest pending `scan_logs.scheduled_at` per event (v0.7.0 data source change; same column, new backing store). |
| 持仓 (Positions) | Live positions across markets with floating P&L |
| Wallet | Cash + positions equity + ledger (topup / withdraw / reset) |
| History | Realized-P&L ledger — one row per SELL / RESOLVE event |
| 归档 (menu 5) | Events the user was monitoring when they closed (replaces v0.6.0's Notifications view) |

- Worker threads for async scan/analysis (no UI blocking)
- Auto-refresh current view when daemon is alive
- Detail views: score breakdown, AI analysis versions, trade dialog (Buy/Sell tabs)
  with real-time CLOB pricing and live fee preview
- Always restarts daemon on launch (picks up latest code); skips when no
  monitored events exist
