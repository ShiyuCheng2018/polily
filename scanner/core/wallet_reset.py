"""Reset wallet-side tables only. Events / markets / analyses preserved.

What reset wipes (single transaction):
- positions           — live exposure
- wallet_transactions — full ledger incl. MIGRATION bookmark
- paper_trades WHERE status='open' — legacy open trades; required so the
  auto-migration hook in PolilyDB.__init__ does NOT re-aggregate them after
  reset. Resolved paper_trades stay as read-only historical record.
- wallet              — singleton row

Then re-inserts the wallet at `starting_balance` with zeroed topup/withdraw
totals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB


def reset_wallet(db: PolilyDB, *, starting_balance: float) -> None:
    """Wipe wallet-side state and re-seed the wallet at `starting_balance`."""
    if starting_balance <= 0:
        raise ValueError(
            f"starting_balance must be positive, got {starting_balance}"
        )
    now = datetime.now(UTC).isoformat()
    with db.conn:
        db.conn.execute("DELETE FROM positions")
        db.conn.execute("DELETE FROM wallet_transactions")
        # Contract (see migration_v060): open paper_trades MUST be deleted so
        # that post-reset PolilyDB init does not re-migrate them.
        db.conn.execute("DELETE FROM paper_trades WHERE status='open'")
        db.conn.execute("DELETE FROM wallet")
        db.conn.execute(
            "INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) "
            "VALUES (1,?,?,0,0,?,?)",
            (starting_balance, starting_balance, now, now),
        )
