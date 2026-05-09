## 4. Data Freshness

Polily exposes data with four distinct freshness profiles. Knowing which is which prevents you from over-trusting a stale value or wasting time re-querying a fresh stream.

### Bucket 1 — Real-time stream (≤ 30 s old)

Updated by the global poll job every 30 s on every **monitored** market (`event_monitors.auto_monitor = 1`). Stream columns on `markets`:

- Pricing: `yes_price`, `no_price`, `best_bid`, `best_ask`, `spread`, `last_trade_price`
- Depth / book: `bid_depth`, `ask_depth`, `book_bids` (JSON), `book_asks` (JSON), `recent_trades` (JSON)
- Volume: `volume`
- Timestamp: `updated_at` (ISO 8601 UTC — this is the actual column, **not** `last_updated`)

If you query the same row 5 seconds apart you may see different values; that is correct, not a race condition. Use a timestamp-anchored reference when narrating: *"at 20:51:25, BTC-30k YES sat at 0.42"*. Treat in-window drift as a narrative input (*"during my analysis YES drifted +14 bps over 2 min, reflecting moderate buying pressure"*) — never as a database race or a polily bug.

**Unmonitored events are not in this bucket.** Their pricing columns reflect whatever was last fetched (scan time or last `auto_monitor=1` window). If `event_monitors.auto_monitor = 0` for an event, every "live" price you see may be hours old.

### Bucket 2 — Periodic computed (≤ 30 s lag for monitored events; static for unmonitored)

Recomputed by `polily/daemon/score_refresh.py` each poll cycle, **but only for events with `event_monitors.auto_monitor = 1`**. Columns:

- `markets.structure_score` — per-market 0–100 score
- `markets.score_breakdown` — JSON exposing per-dimension contributions plus optional `implied_fair_value` (negRisk events) and `mispricing_signal` / `mispricing_details` (crypto markets, derived from Binance underlying via `polily.scan.mispricing`)
- `events.structure_score` — event-level 6-dim aggregate (recomputed when child market scores change)

**Caveat:** `events.score_breakdown` does **not** exist as a column — score_breakdown JSON only lives on `markets` and on `analyses` (snapshot at analysis time). If you need event-level dimension breakdown, query the constituent markets and aggregate yourself.

For unmonitored events, these computed values are frozen at the moment the event was last scanned (or last had monitoring enabled). Don't trust the freshness without checking `markets.updated_at` against the current time.

### Bucket 3 — External / fresh at analysis time

What you can fetch live during this analysis run via your tools:

- **`WebSearch`** — live web pages (polls, news, betting odds aggregators, on-chain block explorers)
- **`Bash`** — anything: `curl https://...` to hit external APIs directly (Polymarket Gamma, sportsbook APIs, oracle feeds), `sqlite3 <db>` to query polily's DB, etc.
- **`Read`** — local file system (e.g. `official_strategy_path` for fallback per §8)

Cost is non-trivial — `WebSearch` and `Bash curl` add seconds per call. Use them when the question genuinely needs live data, not by default.

**What you cannot call directly:**

- Binance / ccxt for crypto vol underlying — that runs in `polily.scan.mispricing` at scan time and `daemon/score_refresh.py` per poll for monitored events; results land in `markets.score_breakdown.mispricing_signal`. If you want fresh BTC/ETH spot, shell out via `Bash` (`curl https://api.binance.com/...`).
- Sub-agent dispatch — there is no `Task` tool; you are a single claude session.

### Bucket 4 — Static (set once, doesn't change)

- `events.event_metadata` (JSON; may include `context_description`)
- `events.tags`, `events.market_type`, `events.resolution_source`
- `events.start_date`, `events.end_date`
- DB schema itself (column names, CHECK constraints) — see §3
- Polily mechanics — see §2
- Pre-existing rows in `analyses` (immutable history; new rows append per analysis)

When you observe a value changing across two reads in the same analysis, it is bucket 1 or 2 — not bucket 4, not a bug. Mention the timestamps in your narrative if it materially affected your reasoning.
