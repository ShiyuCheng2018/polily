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
    polymarket_category TEXT,
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

-- 6. Paper trades
CREATE TABLE IF NOT EXISTS paper_trades (
    id                  TEXT PRIMARY KEY,
    event_id            TEXT NOT NULL REFERENCES events(event_id),
    market_id           TEXT NOT NULL REFERENCES markets(market_id),
    title               TEXT NOT NULL,
    side                TEXT NOT NULL CHECK(side IN ('yes','no')),
    entry_price         REAL NOT NULL,
    position_size_usd   REAL NOT NULL,
    structure_score     REAL,
    mispricing_signal   TEXT,
    scan_id             TEXT,
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK(status IN ('open','resolved')),
    resolved_result     TEXT CHECK(resolved_result IN ('yes','no')),
    paper_pnl           REAL,
    friction_adjusted_pnl REAL,
    marked_at           TEXT NOT NULL,
    resolved_at         TEXT
);

-- 7. Scan logs
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

-- 8. Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    event_id            TEXT,
    market_id           TEXT,
    title               TEXT NOT NULL,
    body                TEXT NOT NULL,
    trigger_source      TEXT,
    action_result       TEXT,
    is_read             INTEGER NOT NULL DEFAULT 0,
    read_at             TEXT
);

-- 9. Wallet (singleton)
CREATE TABLE IF NOT EXISTS wallet (
    id                  INTEGER PRIMARY KEY CHECK(id = 1),  -- enforces singleton: only id=1 ever exists
    cash_usd            REAL NOT NULL,
    starting_balance    REAL NOT NULL,
    topup_total         REAL NOT NULL DEFAULT 0.0,
    withdraw_total      REAL NOT NULL DEFAULT 0.0,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

-- 10. Positions (aggregated)
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

-- 11. Wallet transactions (append-only ledger)
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
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_event ON paper_trades(event_id);
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read) WHERE is_read = 0;
CREATE INDEX IF NOT EXISTS idx_positions_event ON positions(event_id);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_created ON wallet_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_event ON wallet_transactions(event_id);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_type ON wallet_transactions(type);
"""


class PolilyDB:
    """Unified SQLite database. Use as context manager."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _init_schema(self):
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()
