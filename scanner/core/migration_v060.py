"""One-time v0.5.x → v0.6.0 migration.

Called automatically from PolilyDB._init_schema (see db.py). Idempotent.

Responsibilities:
1. Ensure the wallet singleton exists, seeded with `starting_balance`.
2. If the MIGRATION bookmark is not yet present AND the legacy `paper_trades`
   table has rows, aggregate open trades by (market_id, side) into the new
   `positions` table using weighted-average cost basis, then insert the
   bookmark so subsequent calls short-circuit.

Design note on the bookmark: we only insert the MIGRATION row when legacy
`paper_trades` data exists. Fresh installs (no paper_trades ever) are NOT
bookmarked — this keeps `wallet_transactions` empty on fresh databases, a
property the wallet/trade_engine test suites depend on. The bookmark is
still the authoritative "did we migrate real data?" signal for real
v0.5.x → v0.6.0 upgrades.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB


def migrate_if_needed(db: PolilyDB, *, starting_balance: float = 100.0) -> None:
    """Ensure wallet singleton exists and migrate legacy paper_trades once."""
    now = datetime.now(UTC).isoformat()

    # Step 1: wallet singleton (idempotent).
    _ensure_wallet(db, starting_balance=starting_balance, now=now)

    # Step 2: aggregation gated by bookmark.
    if _already_migrated(db):
        db.conn.commit()
        return

    # Step 3: skip bookmark insertion for genuinely fresh installs.
    has_any_paper_trades = db.conn.execute(
        "SELECT 1 FROM paper_trades LIMIT 1"
    ).fetchone() is not None
    if not has_any_paper_trades:
        db.conn.commit()
        return

    # Step 4: aggregate open paper_trades by (market_id, side).
    # Filter guards:
    # - entry_price > 0: prevents division-by-zero on corrupt rows
    # - entry_price < 1: real trades always had 0 < price < 1 on Polymarket
    # - position_size_usd > 0: rejects negative/zero cost basis entries
    rows = db.conn.execute("""
        SELECT market_id, side, event_id, MAX(title) AS title,
               SUM(position_size_usd / entry_price) AS shares,
               SUM(position_size_usd) / SUM(position_size_usd / entry_price) AS avg_cost,
               SUM(position_size_usd) AS cost_basis,
               MIN(marked_at) AS opened_at
        FROM paper_trades
        WHERE status = 'open'
          AND entry_price > 0 AND entry_price < 1
          AND position_size_usd > 0
        GROUP BY market_id, side
    """).fetchall()

    # Step 5: write positions + bookmark atomically. `with db.conn:` commits on
    # success, rolls back on exception — guards against partial aggregation if
    # any single INSERT raises (UNIQUE conflict, FK violation, etc.).
    with db.conn:
        for r in rows:
            db.conn.execute(
                """INSERT INTO positions
                (market_id,side,event_id,shares,avg_cost,cost_basis,realized_pnl,title,opened_at,updated_at)
                VALUES (?,?,?,?,?,?,0,?,?,?)""",
                (
                    r["market_id"], r["side"], r["event_id"],
                    r["shares"], r["avg_cost"], r["cost_basis"],
                    r["title"] or "(migrated)", r["opened_at"] or now, now,
                ),
            )

        # Bookmark is the authoritative "migration ran" signal.
        n_resolved = db.conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE status='resolved'"
        ).fetchone()[0]
        notes = (
            f"v0.6.0 wallet system initialized with ${starting_balance}. "
            f"Aggregated {len(rows)} open positions from legacy paper_trades. "
            f"{n_resolved} resolved paper_trades remain as read-only history."
        )
        db.conn.execute(
            "INSERT INTO wallet_transactions (created_at,type,amount_usd,balance_after,notes) "
            "VALUES (?,?,0,?,?)",
            (now, "MIGRATION", starting_balance, notes),
        )


def _ensure_wallet(db: PolilyDB, *, starting_balance: float, now: str) -> None:
    """No-op if the wallet row already exists.

    Starting-balance changes across runs do NOT propagate to the existing
    wallet — otherwise a config edit would silently clobber real cash state.
    To rebase on a new starting_balance, use `polily reset --wallet-only`
    (Task 1.9), which explicitly wipes and re-seeds.
    """
    row = db.conn.execute("SELECT id FROM wallet WHERE id=1").fetchone()
    if row is not None:
        return
    db.conn.execute(
        "INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) "
        "VALUES (1,?,?,0,0,?,?)",
        (starting_balance, starting_balance, now, now),
    )


def _already_migrated(db: PolilyDB) -> bool:
    """True if a MIGRATION bookmark exists.

    Not checking wallet existence — `polily reset --wallet-only` (Task 1.9)
    reinserts wallet AND deletes open paper_trades, so the right "did migration
    run?" signal is the bookmark itself.
    """
    row = db.conn.execute(
        "SELECT id FROM wallet_transactions WHERE type='MIGRATION' LIMIT 1"
    ).fetchone()
    return row is not None
