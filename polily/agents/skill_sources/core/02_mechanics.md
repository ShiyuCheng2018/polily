## 2. Polily Mechanics

Polily is structured around two domain concepts:

- **Event** (`events` table): a Polymarket event identified by a slug. An event holds metadata (title, end_date, neg_risk flag, market_type, structure_score, tier) and references one or more child markets via `markets.event_id` FK.
- **Market** (`markets` table): a single tradable outcome under an event. Each market has yes_price / no_price / volume / spread / bid_depth / ask_depth, lifecycle state (closed, resolved_outcome ∈ `'yes' | 'no' | 'split' | 'void' | NULL`), and per-market `structure_score` + `score_breakdown` JSON (see §3 for the full column list).

**negRisk events** have multiple mutually-exclusive markets summing to ~1.0 (winner-take-all). For these, each market's `score_breakdown.implied_fair_value` is the implied price under the negRisk completeness identity:

    implied_fair_value(M) = 1 − Σ(other markets' yes_price)

This is computed at scan time and refreshed each daemon score-refresh cycle. Use it as a structural anchor for negRisk reasoning; for crypto markets, use `score_breakdown.mispricing_signal` instead.

**Daemon poll cycle**: a single global poll job runs every **30 s** on a dedicated APScheduler executor. Each tick: fetches prices for every market the user is monitoring, records movement signals into `movement_log`, drains overdue `scan_logs.next_check_at` rows by dispatching AI analyses, and may auto-trigger a movement-driven analysis if magnitude × quality crosses thresholds.

**Trigger sources** for an analysis (column `scan_logs.trigger_source` and `analyses.trigger_source`):

- `manual` — user clicked "AI analysis" in the TUI (event detail page key `a`)
- `scan` — initial scoring of a freshly-pasted URL (one-time per event)
- `scheduled` — daemon dispatched at the `next_check_at` time the previous analysis requested
- `movement` — significant price movement on a monitored market crossed the daemon's magnitude/quality thresholds

**Scoring** — polily has **two separate scores**, both 0–100, both stored as `structure_score`:

**Per-market `markets.structure_score`** (5 dimensions, weights are market_type-specific; see `_TYPE_WEIGHTS` in `polily/scan/scoring.py`):

1. **Liquidity Structure** — spread + log-scale depth + bid/ask balance
2. **Objective Verifiability** — resolution-source quality (baseline 0)
3. **Probability Space** — symmetric `min(p, 1-p)` linear
4. **Time Structure** — sweet spot [1, 5] days + catalyst proximity
5. **Trading Friction** — pure friction 6-tier
   *(+ **Net Edge** crypto-only bonus dim — `|deviation% − round_trip_friction|`, 0 for non-crypto)*

`markets.score_breakdown` JSON exposes each dimension's contribution plus optional fields: `mispricing_signal` / `mispricing_details` (crypto), `implied_fair_value` (negRisk).

**Event-level `events.structure_score`** is computed independently by `compute_event_quality_score` (see `polily/scan/event_scoring.py`) — **NOT** an aggregate of child markets. Six dimensions:

1. **Information Value** (0–20) — does the event reward research?
2. **Liquidity Aggregate** (0–20) — total depth across child markets
3. **Resolution Quality** — same source quality as per-market dim 2, but at event level
4. **Consistency** — internal consistency of child market prices (negRisk-aware)
5. **Time Window** — same sweet-spot logic at event level
6. **Best Market Quality** — quality of the strongest child market

When narrating, both scores measure **tradability** (whether the market / event is *tradeable*), not **trade quality** (whether you should trade) — never conflate the two.
