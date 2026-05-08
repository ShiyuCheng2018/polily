## 3. Database Schema

The Polily SQLite database lives at the path listed in §5. Use the `Bash` tool with `sqlite3` to query it directly:

    sqlite3 <db_path> "SELECT ... FROM ... WHERE ..."

Compose your own SELECTs as needed — no canned templates here. Below is the schema; column meanings are what you need to write good queries.

### Table: `events`
- `event_id` TEXT PRIMARY KEY (the slug)
- `title` TEXT
- `slug` TEXT (mirrors event_id; both populated)
- `end_date` TEXT (ISO 8601)
- `closed` INTEGER (boolean: 0 / 1)
- `active` INTEGER (boolean)
- `neg_risk` INTEGER (boolean)
- `neg_risk_market_id` TEXT (the umbrella market id when neg_risk = 1)
- `market_count` INTEGER
- `volume`, `liquidity`, `open_interest`, `competitive` REAL
- `tags` TEXT (JSON array)
- `market_type` TEXT (e.g., crypto / political / sports / economic)
- `event_metadata` TEXT (JSON: optional context_description and other notes)
- `structure_score` REAL (0–100 tradability score)
- `tier` TEXT (A / B / C / D)
- `user_status` TEXT
- `created_at`, `updated_at` TEXT (ISO 8601)

### Table: `markets`
- `market_id` TEXT PRIMARY KEY
- `event_id` TEXT (FK → events)
- `question` TEXT
- `yes_price`, `no_price` REAL
- `volume` REAL
- `closed` INTEGER (boolean)
- `resolved_outcome` TEXT NULL ("yes" / "no" / NULL while open)
- `last_updated` TEXT (ISO 8601)

### Table: `positions`
Aggregated holdings: one row per (market_id, side). Used for paper trading.
- `market_id` TEXT
- `side` TEXT ("yes" or "no")
- `quantity` REAL (shares)
- `avg_cost` REAL (weighted-average entry price)
- `event_id` TEXT
- `opened_at` TEXT
- PRIMARY KEY `(market_id, side)`

### Table: `wallet`
Single-row snapshot.
- `id` INTEGER PRIMARY KEY (always 1)
- `cash_balance` REAL
- `last_updated` TEXT

### Table: `wallet_transactions`
Append-only ledger.
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `tx_type` TEXT (`BUY` / `SELL` / `FEE` / `TOPUP` / `WITHDRAW` / `RESET` / `RESOLVE`)
- `event_id`, `market_id` TEXT NULL
- `amount` REAL (sign: positive = cash in, negative = cash out)
- `realized_pnl` REAL NULL (set on SELL/RESOLVE)
- `created_at` TEXT

### Table: `scan_logs`
Per-event analysis history with scheduling.
- `scan_id` TEXT PRIMARY KEY
- `event_id` TEXT
- `trigger_source` TEXT (`scan` / `movement` / `manual` / `scheduled`)
- `status` TEXT (`pending` / `running` / `ok` / `failed`)
- `scheduled_at` TEXT NULL (when this scan was scheduled to run; UTC)
- `next_check_at` TEXT NULL (next dispatch time; UTC)
- `next_check_reason` TEXT
- `created_at`, `completed_at` TEXT
- `error_message` TEXT NULL

### Table: `movement_log`
Per-tick movement records (one row per significant price tick on a monitored market).
- `id` INTEGER PRIMARY KEY AUTOINCREMENT
- `event_id` TEXT NOT NULL, `market_id` TEXT
- `created_at` TEXT NOT NULL (ISO 8601)
- `yes_price`, `no_price`, `prev_yes_price` REAL
- `trade_volume`, `bid_depth`, `ask_depth`, `spread` REAL
- `magnitude` REAL — movement size signal
- `quality` REAL — movement quality / confidence
- `label` TEXT enum: `'consensus' | 'whale_move' | 'slow_build' | 'noise'`
- `triggered_analysis` INTEGER (boolean) — whether this row spawned an AI analysis
- `snapshot` TEXT (JSON, full pricing snapshot)

### Table: `analyses`
Versioned AI analyses per event. Composite PRIMARY KEY `(event_id, version)`.
- `event_id` TEXT NOT NULL REFERENCES `events(event_id)`
- `version` INTEGER NOT NULL (1-indexed, monotonically increasing per event)
- `created_at` TEXT NOT NULL
- `trigger_source` TEXT (`manual` / `scan` / `scheduled` / `movement`)
- `prices_snapshot` TEXT (JSON of yes/no prices at analysis time)
- `narrative_output` TEXT — for `narrative_format='json'` (legacy v0.11.x): JSON-encoded NarrativeWriterOutput dict. For `narrative_format='markdown'` (v0.12.0+): full raw markdown including YAML frontmatter at top
- `narrative_format` TEXT (`'json'` | `'markdown'`) — added in v0.12.0
- `structure_score` REAL NULLABLE
- `score_breakdown` TEXT NULLABLE (JSON of per-dimension scores)
- `mispricing_signal` TEXT (`'none'` | other categorical labels)
- `mispricing_details` TEXT NULLABLE
- `elapsed_seconds` REAL

### Table: `event_monitors`
Per-event monitoring state (user-intent flag only; scheduling moved to `scan_logs` in v0.7.0).
- `event_id` TEXT PRIMARY KEY REFERENCES `events(event_id)`
- `auto_monitor` INTEGER (boolean)
- `price_snapshot` TEXT (JSON)
- `notes` TEXT
- `updated_at` TEXT

### Table: `config`
Flat key-value knob storage with **JSON-encoded values**. Writes go through `polily.core.config_store.upsert(db, key_path, value)`.
- `key_path` TEXT PRIMARY KEY (dotted path, e.g., `wallet.starting_balance` or `active_strategy`)
- `value` TEXT NOT NULL (JSON-encoded — decode via `json.loads(value)`)
- `updated_at` TEXT NOT NULL

### Table: `user_strategy`
Single-row table holding the user's custom analysis strategy (v0.12.0+).
- `id` INTEGER PRIMARY KEY (always 1; `CHECK (id = 1)` enforces single-slot)
- `text` TEXT (full markdown body of the user's strategy)
- `updated_at` TEXT
