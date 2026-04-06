"""Unified SQLite database for Polily."""

import sqlite3
from pathlib import Path

_SCHEMA = """
-- 1. Market states
CREATE TABLE IF NOT EXISTS market_states (
    market_id       TEXT PRIMARY KEY,
    status          TEXT NOT NULL CHECK(status IN ('buy_yes', 'buy_no', 'watch', 'pass', 'closed')),
    title           TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL,
    next_check_at   TEXT,
    watch_reason    TEXT,
    watch_sequence  INTEGER NOT NULL DEFAULT 0,
    price_at_watch  REAL,
    auto_monitor    INTEGER NOT NULL DEFAULT 0,
    resolution_time TEXT,
    market_type     TEXT,
    clob_token_id_yes TEXT,
    condition_id    TEXT,
    wc_watch_reason TEXT,
    wc_better_entry TEXT,
    wc_trigger_event TEXT,
    wc_invalidation TEXT,
    notes           TEXT NOT NULL DEFAULT ''
);

-- 2. AI analysis versions
CREATE TABLE IF NOT EXISTS analyses (
    market_id       TEXT NOT NULL,
    version         INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    market_title    TEXT NOT NULL,
    yes_price_at_analysis REAL,
    trigger_source  TEXT NOT NULL DEFAULT 'manual'
                    CHECK(trigger_source IN ('manual', 'scan', 'scheduled', 'movement')),
    watch_sequence  INTEGER NOT NULL DEFAULT 0,
    price_at_watch  REAL,
    analyst_output  TEXT NOT NULL,
    narrative_output TEXT NOT NULL,
    structure_score REAL,
    score_breakdown TEXT,
    mispricing_signal TEXT NOT NULL DEFAULT 'none',
    mispricing_details TEXT,
    elapsed_seconds REAL NOT NULL DEFAULT 0.0,
    PRIMARY KEY (market_id, version)
);

-- 3. Scan logs
CREATE TABLE IF NOT EXISTS scan_logs (
    scan_id         TEXT PRIMARY KEY,
    type            TEXT NOT NULL DEFAULT 'scan'
                    CHECK(type IN ('scan', 'analyze')),
    market_id       TEXT,
    market_title    TEXT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    total_elapsed   REAL NOT NULL DEFAULT 0.0,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK(status IN ('running', 'completed', 'failed')),
    error           TEXT,
    total_markets   INTEGER NOT NULL DEFAULT 0,
    research_count  INTEGER NOT NULL DEFAULT 0,
    watchlist_count INTEGER NOT NULL DEFAULT 0,
    filtered_count  INTEGER NOT NULL DEFAULT 0,
    steps           TEXT
);

-- 4. Paper trades
CREATE TABLE IF NOT EXISTS paper_trades (
    id              TEXT PRIMARY KEY,
    market_id       TEXT NOT NULL,
    title           TEXT NOT NULL,
    market_type     TEXT,
    side            TEXT NOT NULL CHECK(side IN ('yes', 'no')),
    entry_price     REAL NOT NULL,
    structure_score REAL,
    mispricing_signal TEXT,
    scan_id         TEXT,
    status          TEXT NOT NULL DEFAULT 'open'
                    CHECK(status IN ('open', 'resolved')),
    resolved_result TEXT CHECK(resolved_result IN ('yes', 'no')),
    paper_pnl       REAL,
    friction_adjusted_pnl REAL,
    marked_at       TEXT NOT NULL,
    resolved_at     TEXT,
    position_size_usd REAL NOT NULL
);

-- 5. Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT NOT NULL,
    market_id       TEXT,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    trigger_source  TEXT,
    action_result   TEXT,
    is_read         INTEGER NOT NULL DEFAULT 0,
    read_at         TEXT
);

-- 6. Movement log (lightweight price poll snapshots)
CREATE TABLE IF NOT EXISTS movement_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    market_id       TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    yes_price       REAL,
    prev_yes_price  REAL,
    trade_volume    REAL NOT NULL DEFAULT 0.0,
    bid_depth       REAL NOT NULL DEFAULT 0.0,
    ask_depth       REAL NOT NULL DEFAULT 0.0,
    spread          REAL,
    magnitude       REAL NOT NULL DEFAULT 0.0,
    quality         REAL NOT NULL DEFAULT 0.0,
    label           TEXT NOT NULL DEFAULT 'noise'
                    CHECK(label IN ('consensus', 'whale_move', 'slow_build', 'noise')),
    triggered_analysis INTEGER NOT NULL DEFAULT 0,
    snapshot        TEXT NOT NULL DEFAULT '{}'
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_analyses_market ON analyses(market_id);
CREATE INDEX IF NOT EXISTS idx_states_monitor ON market_states(auto_monitor)
    WHERE auto_monitor = 1;
CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications(is_read)
    WHERE is_read = 0;
CREATE INDEX IF NOT EXISTS idx_paper_trades_status ON paper_trades(status);
CREATE INDEX IF NOT EXISTS idx_paper_trades_market ON paper_trades(market_id);
CREATE INDEX IF NOT EXISTS idx_movement_log_market ON movement_log(market_id, created_at);
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
