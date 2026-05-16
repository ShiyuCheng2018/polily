## 3. Database Schema

The Polily SQLite database lives at the path listed in §5. Use the `Bash` tool with `sqlite3` to query it directly:

    sqlite3 <db_path> "SELECT ... FROM ... WHERE ..."

Compose your own SELECTs as needed — no canned templates here. Below is the schema; column meanings are what you need to write good queries. Column names are exact — match them precisely or your query returns 0 rows.

### Table: `events`

The Polymarket event identified by a slug. One row per event; references one or more `markets` via `markets.event_id` FK.

- `event_id` TEXT PRIMARY KEY (the slug)
- `title` TEXT NOT NULL
- `slug` TEXT
- `description` TEXT
- `resolution_source` TEXT — verbatim Polymarket-provided source URL/text; empty / vague values lower the Objectivity dimension score
- `neg_risk` INTEGER (boolean) — 1 = winner-take-all multi-market event
- `neg_risk_market_id` TEXT — umbrella market id when `neg_risk = 1`
- `market_count` INTEGER
- `start_date`, `end_date` TEXT (ISO 8601)
- `volume`, `liquidity`, `open_interest`, `competitive` REAL
- `tags` TEXT (JSON array)
- `market_type` TEXT — e.g. `crypto / political / sports / economic / default`
- `event_metadata` TEXT (JSON; may contain `context_description` and other notes)
- `structure_score` REAL — event-level 0–100 score (computed by `compute_event_quality_score`; **not** an aggregate of child markets — see §2)
- `tier` TEXT — `A / B / C / D` based on score thresholds
- `user_status` TEXT
- `active`, `closed` INTEGER (booleans)
- `created_at`, `updated_at` TEXT (ISO 8601)

### Table: `markets`

A single tradable outcome under an event. Many real-time-streamed columns (see §4 freshness rules).

**Identity / outcome:**
- `market_id` TEXT PRIMARY KEY
- `event_id` TEXT NOT NULL REFERENCES `events(event_id)`
- `question` TEXT NOT NULL
- `slug`, `description`, `group_item_title`, `group_item_threshold` TEXT
- `outcomes` TEXT (JSON array; default `["Yes","No"]`)
- `condition_id`, `question_id` TEXT — Polymarket on-chain identifiers
- `clob_token_id_yes`, `clob_token_id_no` TEXT — CLOB token IDs

**negRisk:**
- `neg_risk` INTEGER (boolean) — 1 = part of a winner-take-all set
- `neg_risk_request_id`, `neg_risk_other` (INT) TEXT — negRisk auction metadata

**Real-time pricing** (updated every ~30 s by daemon poll):
- `yes_price`, `no_price` REAL
- `best_bid`, `best_ask`, `spread`, `last_trade_price` REAL
- `bid_depth`, `ask_depth` REAL — USD-denominated cumulative depth
- `book_bids`, `book_asks` TEXT (JSON arrays of `[price, size]` levels)
- `recent_trades` TEXT (JSON array)
- `volume`, `liquidity` REAL

**Trading parameters:**
- `order_min_tick_size` REAL
- `accepting_orders` INTEGER (boolean)
- `fees_enabled` INTEGER (boolean) — authoritative gate for taker fee
- `fee_rate` REAL — fee schedule coefficient; NULL when no schedule

**Scoring:**
- `structure_score` REAL — per-market 0–100 (5-dim system; see §2)
- `score_breakdown` TEXT (JSON) — exposes each dimension's contribution; for negRisk events this includes `implied_fair_value`; for crypto markets it includes `mispricing_signal` / `mispricing_details`

**Lifecycle:**
- `resolved_outcome` TEXT NULL — `'yes' | 'no' | 'split' | 'void' | NULL`
- `active`, `closed` INTEGER (booleans)
- `end_date`, `resolution_source` TEXT
- `created_at`, `updated_at` TEXT

### Table: `analyses`

Versioned AI analyses per event. Composite PRIMARY KEY `(event_id, version)`.

- `event_id` TEXT NOT NULL REFERENCES `events(event_id)`
- `version` INTEGER NOT NULL — 1-indexed, monotonically increasing per event
- `created_at` TEXT NOT NULL
- `trigger_source` TEXT — CHECK constraint enforces `'manual' | 'scan' | 'scheduled' | 'movement'`
- `prices_snapshot` TEXT (JSON) — yes/no prices at analysis time
- `narrative_output` TEXT NOT NULL — for `narrative_format='json'` (legacy v0.11.x): JSON-encoded NarrativeWriterOutput dict. For `narrative_format='markdown'` (v0.12.0+): full raw markdown including YAML frontmatter at top
- `narrative_format` TEXT — `'json' | 'markdown'` (added in v0.12.0)
- `structure_score` REAL NULLABLE — score snapshot at analysis time
- `score_breakdown` TEXT NULLABLE (JSON)
- `mispricing_signal` TEXT — `'none'` or other categorical labels
- `mispricing_details` TEXT NULLABLE
- `elapsed_seconds` REAL — claude CLI total elapsed for this analysis

### Table: `scan_logs`

Per-event analysis dispatch ledger — unified lifecycle for manual / scheduled / movement triggers. **Every analysis run has a corresponding scan_logs row** that gates persistence (atomic `finish_scan` claim).

- `scan_id` TEXT PRIMARY KEY
- `type` TEXT — CHECK `'scan' | 'analyze' | 'add_event'`
- `event_id` TEXT
- `market_title` TEXT
- `started_at`, `finished_at` TEXT (ISO 8601 UTC)
- `total_elapsed` REAL
- `status` TEXT — CHECK `'pending' | 'running' | 'completed' | 'failed' | 'cancelled' | 'superseded'`
- `error` TEXT NULL — failure message when `status='failed'`
- `total_markets`, `research_count`, `watchlist_count`, `filtered_count` INTEGER
- `steps` TEXT (JSON) — per-step trace
- **`scheduled_at` TEXT NULL** — UTC ISO 8601 of when this scan was scheduled to run. **Naming note:** the agent's output field is called `next_check_at` (in YAML frontmatter) but it lands here as `scheduled_at` — same semantic, different name at the storage boundary
- `trigger_source` TEXT — CHECK `'manual' | 'scan' | 'scheduled' | 'movement'`
- `scheduled_reason` TEXT — context for the schedule (mirrors agent's `next_check_reason` field)

### Table: `movement_log`

Per-tick movement records. One row per significant price tick on a monitored market.

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `event_id` TEXT NOT NULL, `market_id` TEXT
- `created_at` TEXT NOT NULL (ISO 8601)
- `yes_price`, `no_price`, `prev_yes_price` REAL
- `trade_volume`, `bid_depth`, `ask_depth`, `spread` REAL
- `magnitude` REAL — movement size signal
- `quality` REAL — movement quality / confidence
- `label` TEXT — CHECK `'consensus' | 'whale_move' | 'slow_build' | 'noise'`
- `triggered_analysis` INTEGER (boolean) — whether this row spawned an AI analysis
- `snapshot` TEXT (JSON) — full pricing snapshot at the tick

### Table: `event_monitors`

Per-event user-intent flag (scheduling moved to `scan_logs` in v0.7.0).

- `event_id` TEXT PRIMARY KEY REFERENCES `events(event_id)`
- `auto_monitor` INTEGER (boolean) — 1 = user wants polily to keep polling
- `price_snapshot` TEXT (JSON)
- `notes` TEXT
- `updated_at` TEXT NOT NULL

### Table: `positions`

Aggregated paper-trading holdings — one row per `(market_id, side)`. Composite PRIMARY KEY `(market_id, side)`. PositionManager is the sole writer.

- `market_id` TEXT NOT NULL REFERENCES `markets(market_id)`
- `side` TEXT — CHECK `'yes' | 'no'`
- `event_id` TEXT NOT NULL REFERENCES `events(event_id)`
- **`shares` REAL NOT NULL** — quantity of YES or NO shares held (column name is `shares`, not `quantity`)
- `avg_cost` REAL NOT NULL — weighted-average entry price
- `cost_basis` REAL NOT NULL — `= shares × avg_cost` (kept in sync by PositionManager)
- `realized_pnl` REAL — cumulative realized P&L on partial closes
- `title` TEXT NOT NULL — denormalized market title (snapshot for display)
- `opened_at`, `updated_at` TEXT NOT NULL

### Table: `wallet`

Singleton paper-trading cash account. `id INTEGER PRIMARY KEY CHECK(id = 1)` enforces single-row.

- `id` INTEGER — always 1
- **`cash_usd` REAL NOT NULL** — current cash balance (column name is `cash_usd`, not `cash_balance`)
- `starting_balance` REAL NOT NULL
- `topup_total`, `withdraw_total` REAL — running totals from ledger
- `created_at`, `updated_at` TEXT NOT NULL

### Table: `wallet_transactions`

Append-only paper-trading ledger. INTEGER PRIMARY KEY AUTOINCREMENT. **`market_id` and `event_id` are stored WITHOUT FK constraints** — the ledger must survive market soft-close.

- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `created_at` TEXT NOT NULL
- **`type` TEXT** — CHECK `'TOPUP' | 'WITHDRAW' | 'BUY' | 'SELL' | 'RESOLVE' | 'FEE' | 'MIGRATION'` (column name is `type`, not `tx_type`)
- `market_id`, `event_id` TEXT NULL
- `side` TEXT NULL — CHECK `'yes' | 'no'`
- `shares`, `price` REAL NULL
- **`amount_usd` REAL NOT NULL** — sign convention: positive = cash IN to wallet, negative = cash OUT (column name is `amount_usd`, not `amount`)
- `fee_usd` REAL NOT NULL DEFAULT 0
- `balance_after` REAL NOT NULL — wallet cash after this tx
- `realized_pnl` REAL NULL — set on `SELL` / `RESOLVE`; null on `TOPUP / WITHDRAW / FEE / MIGRATION`
- `notes` TEXT NULL

### Table: `config`

DB-canonical config storage. Flat `key_path → JSON-encoded value`. Writes go through `polily.core.config_store.upsert(db, key_path, value)` which validates against `PolilyConfig` before insert.

- `key_path` TEXT PRIMARY KEY — dotted path (e.g. `wallet.starting_balance`, `active_strategy`, `movement.magnitude_threshold`)
- `value` TEXT NOT NULL — JSON-encoded; decode via `json.loads(value)` (a string knob like `active_strategy='official'` is stored as `"official"` literally, including the quotes)
- `updated_at` TEXT NOT NULL

### Table: `user_prefs`

Lightweight key-value store for runtime UI preferences (separate from `config` — these are not Pydantic-validated).

- `key` TEXT PRIMARY KEY — e.g. `language` (TUI F2 toggle persists here)
- `value` TEXT NOT NULL — raw string (no JSON encoding)
- `updated_at` TEXT NOT NULL

### Table: `user_strategy`

Single-row table holding the user's custom analysis strategy (v0.12.0+). `id INTEGER PRIMARY KEY CHECK(id = 1)` enforces single-slot.

- `id` INTEGER — always 1
- `text` TEXT NOT NULL — full markdown body of the user's strategy (may be `''` empty when user hasn't authored one)
- `updated_at` TEXT NOT NULL
