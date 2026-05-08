"""Unified SQLite database for Polily."""

import contextlib
import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

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

-- 3. Event monitors (v0.7.0: scheduling moved to scan_logs; this table is user-intent only)
CREATE TABLE IF NOT EXISTS event_monitors (
    event_id            TEXT PRIMARY KEY REFERENCES events(event_id),
    auto_monitor        INTEGER NOT NULL DEFAULT 0,
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

-- 6. Scan logs (v0.7.0: unified lifecycle for manual / scheduled / movement AI analyses)
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
                        CHECK(status IN ('pending','running','completed','failed','cancelled','superseded')),
    error               TEXT,
    total_markets       INTEGER NOT NULL DEFAULT 0,
    research_count      INTEGER NOT NULL DEFAULT 0,
    watchlist_count     INTEGER NOT NULL DEFAULT 0,
    filtered_count      INTEGER NOT NULL DEFAULT 0,
    steps               TEXT,
    -- v0.7.0 scheduler fields
    scheduled_at        TEXT,
    trigger_source      TEXT NOT NULL DEFAULT 'manual'
                        CHECK(trigger_source IN ('manual','scan','scheduled','movement')),
    scheduled_reason    TEXT
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
CREATE TABLE IF NOT EXISTS user_prefs (
    key                 TEXT PRIMARY KEY,
    value               TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

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

-- 11. Config (db-canonical config storage)
-- Flat key_path → JSON-encoded value mapping. PK on key_path lets reset
-- operate at single-leaf granularity and concurrent writes don't collide.
CREATE TABLE IF NOT EXISTS config (
    key_path   TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
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
CREATE INDEX IF NOT EXISTS idx_scan_logs_dispatch ON scan_logs(status, scheduled_at)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_scan_logs_event_status ON scan_logs(event_id, status);
"""


class PolilyDB:
    """Unified SQLite database. Use as context manager."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # _lock: re-entrant lock for serializing sqlite3 access.
        #
        # v0.11.4 introduced this lock as a narrow fix wrapping
        # _run_pending_analysis (poll_job.py) only. v0.11.6 extended
        # protection to ALL DB access via PolilyDB.transaction()
        # (the canonical entry point). Every read/write across the
        # codebase now flows through that context manager, which
        # acquires this lock.
        #
        # Re-entrancy (RLock not Lock): WalletService.execute_buy →
        # wallet.debit → positions.upsert nests `with db.transaction()`
        # blocks on the same thread; non-reentrant Lock would deadlock.
        # Same-thread re-entry is safe; cross-thread re-entry blocks.
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # busy_timeout MUST be set before journal_mode=WAL — on Linux CI,
        # 4-thread SF5 race against `PRAGMA journal_mode=WAL` raised
        # 'database is locked' instantly because no retry budget existed.
        # Setting busy_timeout first gives subsequent pragmas (and all
        # later writes) up to 5s of retry headroom under WAL contention.
        # Required for the SF5 concurrency test in tests/test_config_store.py.
        self.conn.execute("PRAGMA busy_timeout=5000")
        # B1 (v0.10.0): WAL-mode pragma is idempotent across sqlite restarts —
        # only the very first PolilyDB on a fresh file flips journal_mode.
        # On that first init, two processes racing the pragma raise
        # SQLITE_LOCKED (not SQLITE_BUSY), which busy_timeout does NOT
        # retry. Skip the pragma when the connection already reports WAL,
        # and tolerate OperationalError when it doesn't — the loser sees
        # the winner's WAL mode on its next read.
        mode_row = self.conn.execute("PRAGMA journal_mode").fetchone()
        current_mode = mode_row[0] if mode_row else ""
        if str(current_mode).lower() != "wal":
            # Another process may be mid-WAL-init; the loser of the race sees
            # SQLITE_LOCKED, but its subsequent reads/writes still operate
            # against the WAL journal set by the winner — so suppress and
            # continue rather than failing the whole construction.
            with contextlib.suppress(sqlite3.OperationalError):
                self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    @contextmanager
    def transaction(self):
        """v0.11.6 canonical DB access point.

        Acquires self._lock (RLock — re-entrant safe). When NOT
        already inside a transaction, also opens sqlite3's auto-commit
        `with conn:` context (commits on clean exit, rolls back on
        Exception). When ALREADY in a transaction (nested call from
        same thread), yields without re-opening — the outer caller
        owns the transaction boundary.

        Why nested-detection matters (Whis-review Blocker 1, 2026-05-05):
        the naïve `with self._lock: with self.conn: yield self.conn`
        is broken for nested calls. RLock IS re-entrant, but
        `with conn:` is NOT — when the inner block exits cleanly,
        sqlite3's __exit__ COMMITs the in-progress transaction.
        Subsequent outer rollbacks find nothing to roll back. Empirical
        result: outer `_atomic_buy` debits cash → calls inner
        wallet.deduct → inner exits clean → cash committed → outer
        position validation raises → outer "rollback" is a no-op →
        money lost.

        The fix: check `self.conn.in_transaction` and, if true, just
        acquire the lock and yield. Outer scope owns commit/rollback.

        Usage (migration target):

            # Read
            with db.transaction() as conn:
                rows = conn.execute("SELECT ...").fetchall()

            # Single leaf write (no outer transaction)
            with db.transaction() as conn:
                conn.execute("INSERT ...", params)
                # auto-commits on exit; rollback on Exception

            # Nested call — outer owns commit
            def outer():
                with db.transaction() as conn:  # opens transaction
                    conn.execute("UPDATE wallet ...")
                    inner_helper(conn)
                    # outer __exit__ commits (or rolls back on raise)

            def inner_helper(conn):
                with db.transaction() as conn:  # nested — lock-only,
                    conn.execute("INSERT positions ...")  # no auto-commit

        Note: files in `polily/core/trade_engine.py`, the
        `wallet.credit(commit=False)` paths, and the BEGIN IMMEDIATE
        blocks in `polily/core/config.py` + `polily/cli.py` do NOT
        migrate to this primitive — see §1.5.1 of the design doc for
        the carve-out rationale (BaseException handling, cross-process
        race protection). They use `with db._lock:` instead and keep
        their existing explicit transaction code.

        Read-only callers wrap reads in this too — the perf cost is
        negligible (SQLite WAL serializes writes anyway).
        """
        with self._lock:
            if self.conn.in_transaction:
                # Nested call — outer scope owns the transaction
                yield self.conn
            else:
                # Top-level — sqlite3 auto-commit on clean exit;
                # rollback on Exception (NOT BaseException — see
                # carve-out files for BaseException safety)
                with self.conn:
                    yield self.conn

    def __enter__(self) -> "PolilyDB":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _init_schema(self) -> None:
        # v0.7.0 scheduler rework migration — runs BEFORE the schema script so
        # the new `idx_scan_logs_dispatch` / `idx_scan_logs_event_status` indexes
        # (which reference scheduled_at / the new status CHECK) see the rebuilt
        # scan_logs table. Idempotent and a no-op on fresh DBs (detects absence
        # of scan_logs or presence of scheduled_at).
        self._migrate_v070_scheduler()
        self.conn.executescript(_SCHEMA)
        # Drop the legacy paper_trades table on databases that were
        # upgraded from <= v0.6.0. Idempotent — no-op on fresh DBs.
        self.conn.execute("DROP TABLE IF EXISTS paper_trades")
        # Drop the legacy notifications table on databases that were
        # upgraded from <= v0.6.1. Idempotent — no-op on fresh DBs.
        self.conn.execute("DROP TABLE IF EXISTS notifications")
        # v0.10.0 (Issue A): normalize any historical scan_logs.scheduled_at
        # rows that were written with a non-UTC TZ suffix (e.g. +08:00 from
        # a Beijing-locale agent run). Idempotent — no-op when all rows are
        # already +00:00. Must run AFTER the schema script so the table
        # exists and AFTER the v0.7.0 migration so column shape is final.
        self._migrate_scheduled_at_to_utc()

        # v0.12.0: analyses backward-compat flag for markdown vs json output.
        # Legacy rows default to 'json' (matches NarrativeWriter pre-v0.12.0
        # behavior); v0.12.0+ writes 'markdown' for new rendering paths.
        # Race-safe: PRAGMA + ALTER is not atomic across processes (TUI +
        # daemon can both run __init__ on first install — see
        # test_db_wal_race.py); swallow the "duplicate column name" error
        # so the second concurrent caller no-ops cleanly.
        try:
            self.conn.execute(
                "ALTER TABLE analyses ADD COLUMN narrative_format TEXT NOT NULL DEFAULT 'json'"
            )
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise

        # v0.12.0: user_strategy table (single-slot, free-form markdown text).
        # CHECK (id = 1) enforces the single-slot contract; future v0.13.0
        # library mode unblocks by removing the constraint and adding a
        # name/slug column.
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_strategy (
                id INTEGER PRIMARY KEY,
                text TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                CHECK (id = 1)
            )
        """)
        self.conn.execute(
            "INSERT OR IGNORE INTO user_strategy (id, text, updated_at) VALUES (1, '', '')"
        )

        # NOTE on active_strategy seeding (v0.12.0):
        # The active_strategy config row is NOT seeded here. PolilyDB.__init__
        # is contractually DDL-only (see test_db_seed::
        # test_wallet_seed_uses_pydantic_default_when_config_table_empty);
        # config seeding is the caller's responsibility via
        # load_config_from_db -> ensure_seeded, which INSERT OR IGNOREs every
        # PolilyConfig leaf including the new active_strategy field. This
        # keeps the "init schema vs seed defaults" boundary clean.

        self.conn.commit()
        self._ensure_wallet_singleton()

    def _migrate_v070_scheduler(self) -> None:
        """Migrate scan_logs + event_monitors to v0.7.0 shape.

        Idempotent: detects prior migration by checking for scheduled_at column.
        Rebuilds scan_logs (CHECK constraint change requires it). Seeds pending
        rows from event_monitors.next_check_at AFTER the rebuild (old schema
        lacks the columns the seed needs).
        """
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(scan_logs)").fetchall()}
        if not cols:
            return  # fresh DB — no scan_logs table yet, schema script will create it
        if "scheduled_at" in cols:
            return  # already migrated

        # 1. Stash event_monitors pending-seed data BEFORE dropping the columns.
        mon_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(event_monitors)").fetchall()}
        seed_rows: list[tuple[str, str, str | None]] = []
        if "next_check_at" in mon_cols:
            seed_rows = [
                (r["event_id"], r["next_check_at"], r["next_check_reason"])
                for r in self.conn.execute(
                    "SELECT event_id, next_check_at, next_check_reason "
                    "FROM event_monitors WHERE next_check_at IS NOT NULL"
                ).fetchall()
            ]

        # 2. Rebuild scan_logs with extended CHECK + new columns.
        self.conn.executescript("""
            ALTER TABLE scan_logs RENAME TO _scan_logs_old;
            CREATE TABLE scan_logs (
                scan_id             TEXT PRIMARY KEY,
                type                TEXT NOT NULL DEFAULT 'scan'
                                    CHECK(type IN ('scan','analyze','add_event')),
                event_id            TEXT,
                market_title        TEXT,
                started_at          TEXT NOT NULL,
                finished_at         TEXT,
                total_elapsed       REAL NOT NULL DEFAULT 0.0,
                status              TEXT NOT NULL DEFAULT 'running'
                                    CHECK(status IN ('pending','running','completed','failed','cancelled','superseded')),
                error               TEXT,
                total_markets       INTEGER NOT NULL DEFAULT 0,
                research_count      INTEGER NOT NULL DEFAULT 0,
                watchlist_count     INTEGER NOT NULL DEFAULT 0,
                filtered_count      INTEGER NOT NULL DEFAULT 0,
                steps               TEXT,
                scheduled_at        TEXT,
                trigger_source      TEXT NOT NULL DEFAULT 'manual'
                                    CHECK(trigger_source IN ('manual','scan','scheduled','movement')),
                scheduled_reason    TEXT
            );
            INSERT INTO scan_logs(
                scan_id, type, event_id, market_title, started_at, finished_at,
                total_elapsed, status, error, total_markets, research_count,
                watchlist_count, filtered_count, steps
            )
            SELECT scan_id, type, event_id, market_title, started_at, finished_at,
                   total_elapsed, status, error, total_markets, research_count,
                   watchlist_count, filtered_count, steps
            FROM _scan_logs_old;
            DROP TABLE _scan_logs_old;
            CREATE INDEX IF NOT EXISTS idx_scan_logs_dispatch ON scan_logs(status, scheduled_at)
                WHERE status = 'pending';
            CREATE INDEX IF NOT EXISTS idx_scan_logs_event_status ON scan_logs(event_id, status);
        """)

        # 3. AFTER the rebuild, seed pending rows directly into the new schema.
        #    Look up events.title so the TUI 待办 zone shows the event name
        #    instead of a "?" placeholder.
        from datetime import UTC, datetime
        now_iso = datetime.now(UTC).isoformat()
        for event_id, next_check_at, reason in seed_rows:
            scan_id = f"mig_{event_id}_{next_check_at[:19].replace(':','').replace('-','')}"
            title_row = self.conn.execute(
                "SELECT title FROM events WHERE event_id=?", (event_id,),
            ).fetchone()
            title = title_row["title"] if title_row else None
            self.conn.execute(
                "INSERT OR IGNORE INTO scan_logs("
                "scan_id, type, event_id, market_title, started_at, status, "
                "trigger_source, scheduled_at, scheduled_reason) "
                "VALUES (?, 'analyze', ?, ?, ?, 'pending', 'scheduled', ?, ?)",
                (scan_id, event_id, title, now_iso, next_check_at, reason),
            )

        # 4. Drop event_monitors columns (SQLite ≥3.35).
        if "next_check_at" in mon_cols:
            self.conn.execute("ALTER TABLE event_monitors DROP COLUMN next_check_at")
        if "next_check_reason" in mon_cols:
            self.conn.execute("ALTER TABLE event_monitors DROP COLUMN next_check_reason")

    def _migrate_scheduled_at_to_utc(self) -> None:
        """v0.10.0 — normalize scan_logs.scheduled_at to canonical UTC ISO.

        Background: scan_logs.scheduled_at historically received whatever TZ
        offset the NarrativeWriter agent emitted (e.g. `+08:00` for a
        Beijing-locale user). The dispatcher's `fetch_overdue_pending` did
        `WHERE scheduled_at <= ?` as TEXT, so `+08:00` sorted greater than
        `+00:00` lexicographically and overdue Beijing rows were never
        dispatched (Issue A regression).

        v0.10.0 normalizes new writes via `_validate_next_check_at` (A.4.1)
        and `insert_pending_scan` (A.4.3). This migration sweeps existing
        rows so they too compare correctly. Idempotent — detection scans
        for any row whose `scheduled_at` does NOT end with `+00:00`; on a
        clean DB there's nothing to do and this is a single SELECT.

        Unparseable timestamps are skipped with a warning rather than
        crashing the whole migration — they will keep failing the
        dispatcher's date compare anyway, and we don't want to brick startup.
        """
        rows = self.conn.execute(
            "SELECT scan_id, scheduled_at FROM scan_logs "
            "WHERE scheduled_at IS NOT NULL AND scheduled_at NOT LIKE '%+00:00'"
        ).fetchall()
        if not rows:
            return
        from datetime import UTC, datetime
        for r in rows:
            scan_id = r["scan_id"]
            sched = r["scheduled_at"]
            try:
                parsed = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=UTC)
                canonical = parsed.astimezone(UTC).isoformat()
                self.conn.execute(
                    "UPDATE scan_logs SET scheduled_at = ? WHERE scan_id = ?",
                    (canonical, scan_id),
                )
            except (ValueError, TypeError):
                logger.warning(
                    "scheduled_at migration: skipping unparseable value %r on scan_id=%s",
                    sched, scan_id,
                )

    def _ensure_wallet_singleton(self) -> None:
        """Seed the wallet row on fresh DBs so downstream code can assume
        `wallet` is non-empty. Idempotent — no-op when the row already
        exists; a config change to `starting_balance` does NOT rebase an
        existing wallet (use `polily reset --wallet-only` for that).

        B2 (v0.10.0) — must NOT call `load_config_from_db` here. That
        path acquires `BEGIN IMMEDIATE`, and from inside `__init__` it
        re-enters the same connection's transaction state and lets the
        TUI+daemon first-init race deadlock. It also forced every test
        constructing a PolilyDB to pay a 46-row config seed.

        Read `wallet.starting_balance` directly from the config table.
        On the very first init (config table empty), fall back to the
        Pydantic default of `WalletConfig`. Callers (cli.py / tui app /
        daemon) are responsible for explicitly invoking
        `load_config_from_db` AFTER construction to apply user edits.
        """
        row = self.conn.execute("SELECT id FROM wallet WHERE id=1").fetchone()
        if row is not None:
            return

        from datetime import UTC, datetime

        # Try to honor a user-edited starting_balance if a prior caller
        # already seeded the config table. If not (fresh install, no
        # explicit load_config_from_db yet), fall back to the Pydantic
        # default — caller is expected to load_config_from_db after
        # construction and the seeded wallet stays in sync because both
        # paths converge on the same default.
        config_row = self.conn.execute(
            "SELECT value FROM config WHERE key_path = 'wallet.starting_balance'",
        ).fetchone()
        if config_row is not None:
            starting = json.loads(config_row[0])
        else:
            from polily.core.config import WalletConfig
            starting = WalletConfig().starting_balance

        now = datetime.now(UTC).isoformat()
        # INSERT OR IGNORE makes the multi-process first-init race safe:
        # if TUI process A and daemon process B both reach this point
        # concurrently (both saw row==None on their respective SELECT),
        # whichever wins the writer lock seeds the row; the other's
        # INSERT no-ops instead of raising IntegrityError. Both processes
        # would have computed the same starting_balance (config row +
        # Pydantic default are deterministic), so the persisted value
        # is identical regardless of who wins.
        self.conn.execute(
            "INSERT OR IGNORE INTO wallet (id,cash_usd,starting_balance,"
            "topup_total,withdraw_total,created_at,updated_at) VALUES (1,?,?,0,0,?,?)",
            (starting, starting, now, now),
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()
