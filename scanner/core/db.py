"""Unified SQLite database for Polily."""

import sqlite3
from pathlib import Path

_SCHEMA = """
-- 1. Events
CREATE TABLE IF NOT EXISTS events (
    event_id            TEXT PRIMARY KEY,
    title               TEXT NOT NULL,
    slug                TEXT,
    description         TEXT,
    resolution_source   TEXT,
    neg_risk            INTEGER NOT NULL DEFAULT 0,
    neg_risk_market_id  TEXT,
    neg_risk_augmented  INTEGER NOT NULL DEFAULT 0,
    market_count        INTEGER NOT NULL DEFAULT 1,
    start_date          TEXT,
    end_date            TEXT,
    image               TEXT,
    volume              REAL,
    liquidity           REAL,
    open_interest       REAL,
    competitive         REAL,
    tags                TEXT NOT NULL DEFAULT '[]',
    market_type         TEXT,
    event_metadata      TEXT,
    structure_score     REAL,
    tier                TEXT,
    user_status         TEXT,
    active              INTEGER NOT NULL DEFAULT 1,
    closed              INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT,
    updated_at          TEXT NOT NULL
);

-- 2. Markets
CREATE TABLE IF NOT EXISTS markets (
    market_id           TEXT PRIMARY KEY,
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    question            TEXT NOT NULL,
    slug                TEXT,
    description         TEXT,
    group_item_title    TEXT,
    group_item_threshold TEXT,
    outcomes            TEXT NOT NULL DEFAULT '["Yes","No"]',
    condition_id        TEXT,
    question_id         TEXT,
    clob_token_id_yes   TEXT,
    clob_token_id_no    TEXT,
    neg_risk            INTEGER NOT NULL DEFAULT 0,
    neg_risk_request_id TEXT,
    neg_risk_other      INTEGER NOT NULL DEFAULT 0,
    resolution_source   TEXT,
    end_date            TEXT,
    volume              REAL,
    liquidity           REAL,
    order_min_tick_size REAL,
    structure_score     REAL,
    score_breakdown     TEXT,
    yes_price           REAL,
    no_price            REAL,
    best_bid            REAL,
    best_ask            REAL,
    spread              REAL,
    last_trade_price    REAL,
    bid_depth           REAL,
    ask_depth           REAL,
    book_bids           TEXT,
    book_asks           TEXT,
    recent_trades       TEXT,
    accepting_orders    INTEGER NOT NULL DEFAULT 1,
    fees_enabled        INTEGER NOT NULL DEFAULT 0,  -- Gamma market.feesEnabled; authoritative gate for taker fee
    fee_rate            REAL,                        -- Gamma market.feeSchedule.rate (coefficient); NULL when no schedule
    resolved_outcome    TEXT CHECK(resolved_outcome IN ('yes','no','split','void')),
    active              INTEGER NOT NULL DEFAULT 1,
    closed              INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT,
    updated_at          TEXT NOT NULL
);

-- 3. Event monitors
CREATE TABLE IF NOT EXISTS event_monitors (
    event_id            TEXT PRIMARY KEY REFERENCES events(event_id),
    auto_monitor        INTEGER NOT NULL DEFAULT 0,
    next_check_at       TEXT,
    next_check_reason   TEXT,
    price_snapshot      TEXT,
    notes               TEXT DEFAULT '',
    updated_at          TEXT NOT NULL
);

-- 4. Analyses
CREATE TABLE IF NOT EXISTS analyses (
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    version             INTEGER NOT NULL,
    created_at          TEXT NOT NULL,
    trigger_source      TEXT NOT NULL DEFAULT 'manual'
                        CHECK(trigger_source IN ('manual','scan','scheduled','movement')),
    prices_snapshot     TEXT NOT NULL DEFAULT '{}',
    narrative_output    TEXT NOT NULL,
    structure_score     REAL,
    score_breakdown     TEXT,
    mispricing_signal   TEXT NOT NULL DEFAULT 'none',
    mispricing_details  TEXT,
    elapsed_seconds     REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (event_id, version)
);

-- 5. Movement log
CREATE TABLE IF NOT EXISTS movement_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            TEXT NOT NULL,
    market_id           TEXT,
    created_at          TEXT NOT NULL,
    yes_price           REAL,
    no_price            REAL,
    prev_yes_price      REAL,
    trade_volume        REAL NOT NULL DEFAULT 0.0,
    bid_depth           REAL NOT NULL DEFAULT 0.0,
    ask_depth           REAL NOT NULL DEFAULT 0.0,
    spread              REAL,
    magnitude           REAL NOT NULL DEFAULT 0.0,
    quality             REAL NOT NULL DEFAULT 0.0,
    label               TEXT NOT NULL DEFAULT 'noise'
                        CHECK(label IN ('consensus','whale_move','slow_build','noise')),
    triggered_analysis  INTEGER NOT NULL DEFAULT 0,
    snapshot            TEXT NOT NULL DEFAULT '{}'
);

-- 6. Scan logs
CREATE TABLE IF NOT EXISTS scan_logs (
    scan_id             TEXT PRIMARY KEY,
    type                TEXT NOT NULL DEFAULT 'scan'
                        CHECK(type IN ('scan','analyze','add_event')),
    event_id            TEXT,
    market_title        TEXT,
    started_at          TEXT NOT NULL,
    finished_at         TEXT,
    total_elapsed       REAL NOT NULL DEFAULT 0.0,
    status              TEXT NOT NULL DEFAULT 'running'
                        CHECK(status IN ('running','completed','failed')),
    error               TEXT,
    total_markets       INTEGER NOT NULL DEFAULT 0,
    research_count      INTEGER NOT NULL DEFAULT 0,
    watchlist_count     INTEGER NOT NULL DEFAULT 0,
    filtered_count      INTEGER NOT NULL DEFAULT 0,
    steps               TEXT
);

-- 8. Wallet (singleton)
CREATE TABLE IF NOT EXISTS wallet (
    id                  INTEGER PRIMARY KEY CHECK(id = 1),  -- enforces singleton: only id=1 ever exists
    cash_usd            REAL NOT NULL,
    starting_balance    REAL NOT NULL,
    topup_total         REAL NOT NULL DEFAULT 0.0,
    withdraw_total      REAL NOT NULL DEFAULT 0.0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- 9. Positions (aggregated)
-- INVARIANT: Polily never hard-deletes events/markets (soft-close via closed=1).
-- FK defaults to NO ACTION; if a future cleanup task deletes markets, positions
-- inserts will raise IntegrityError — that is intentional, positions depend on
-- their anchoring market/event for display and resolution context.
CREATE TABLE IF NOT EXISTS positions (
    market_id           TEXT NOT NULL REFERENCES markets(market_id),
    side                TEXT NOT NULL CHECK(side IN ('yes','no')),
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    shares              REAL NOT NULL,
    avg_cost            REAL NOT NULL,
    cost_basis          REAL NOT NULL,            -- = shares × avg_cost; PositionManager is the sole writer and must update together
    realized_pnl        REAL NOT NULL DEFAULT 0.0,
    title               TEXT NOT NULL,
    opened_at           TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    PRIMARY KEY (market_id, side)
);

-- 10. Wallet transactions (append-only ledger)
-- INVARIANT: market_id and event_id are stored WITHOUT FK constraints — the ledger
-- must survive market soft-close and any future hard-delete cleanup. Orphan lookups
-- via LEFT JOIN are acceptable; this is an accounting record, not relational master data.
CREATE TABLE IF NOT EXISTS wallet_transactions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    type                TEXT NOT NULL CHECK(type IN (
        'TOPUP','WITHDRAW','BUY','SELL','RESOLVE','FEE','MIGRATION'
    )),                                              -- uppercase convention for ledger codes
    market_id           TEXT,
    event_id            TEXT,
    side                TEXT CHECK(side IN ('yes','no')),
    shares              REAL,
    price               REAL,
    amount_usd          REAL NOT NULL,
    fee_usd             REAL NOT NULL DEFAULT 0.0,
    balance_after       REAL NOT NULL,
    realized_pnl        REAL,                        -- null for TOPUP/WITHDRAW/FEE/MIGRATION; set for SELL/RESOLVE
    notes               TEXT
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_markets_event ON markets(event_id);
CREATE INDEX IF NOT EXISTS idx_markets_condition ON markets(condition_id);
CREATE INDEX IF NOT EXISTS idx_events_tier ON events(tier) WHERE closed = 0;
CREATE INDEX IF NOT EXISTS idx_event_monitors_active ON event_monitors(auto_monitor) WHERE auto_monitor = 1;
CREATE INDEX IF NOT EXISTS idx_analyses_event ON analyses(event_id);
CREATE INDEX IF NOT EXISTS idx_movement_event ON movement_log(event_id, created_at);
CREATE INDEX IF NOT EXISTS idx_movement_market ON movement_log(market_id, created_at);
CREATE INDEX IF NOT EXISTS idx_positions_event ON positions(event_id);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_created ON wallet_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_event ON wallet_transactions(event_id);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_type ON wallet_transactions(type);
"""


class PolilyDB:
    """Unified SQLite database. Use as context manager."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def __enter__(self) -> "PolilyDB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        self.conn.executescript(_SCHEMA)
        # Drop the legacy paper_trades table on databases that were
        # upgraded from <= v0.6.0. Idempotent — no-op on fresh DBs.
        self.conn.execute("DROP TABLE IF EXISTS paper_trades")
        # Drop the legacy notifications table on databases that were
        # upgraded from <= v0.6.1. Idempotent — no-op on fresh DBs.
        self.conn.execute("DROP TABLE IF EXISTS notifications")
        self.conn.commit()
        self._ensure_wallet_singleton()

    def _ensure_wallet_singleton(self) -> None:
        """Seed the wallet row on fresh DBs so downstream code can assume
        `wallet` is non-empty. Idempotent — no-op when the row already
        exists; a config change to `starting_balance` does NOT rebase an
        existing wallet (use `polily reset --wallet-only` for that).
        """
        row = self.conn.execute("SELECT id FROM wallet WHERE id=1").fetchone()
        if row is not None:
            return

        import warnings
        from datetime import UTC, datetime

        from scanner.core.config import ScannerConfig
        try:
            from scanner.core.config import load_config
            minimal = Path("config.minimal.yaml")
            example = Path("config.example.yaml")
            if minimal.exists() and example.exists():
                cfg = load_config(minimal, defaults_path=example)
            elif example.exists():
                cfg = load_config(example)
            else:
                cfg = ScannerConfig()
        except Exception as e:
            warnings.warn(
                f"config load failed during wallet seed, using defaults: {e!r}",
                stacklevel=2,
            )
            cfg = ScannerConfig()

        now = datetime.now(UTC).isoformat()
        starting = cfg.wallet.starting_balance
        self.conn.execute(
            "INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,"
            "withdraw_total,created_at,updated_at) VALUES (1,?,?,0,0,?,?)",
            (starting, starting, now, now),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
