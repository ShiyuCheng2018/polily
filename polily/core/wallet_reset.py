"""Reset wallet-side tables only. Events / markets / analyses preserved.

What reset wipes (single transaction):
- positions           — live exposure
- wallet_transactions — full ledger
- wallet              — singleton row

Then re-inserts the wallet at `starting_balance` with zeroed topup/withdraw
totals.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polily.core.db import PolilyDB


def reset_wallet(db: PolilyDB, *, starting_balance: float) -> None:
    """Wipe wallet-side state and re-seed the wallet at `starting_balance`.

    Concurrency: the PolilyDB connection is shared (check_same_thread=False)
    across the poll (1-thread) and AI (5-thread) executors. Callers must
    guarantee no concurrent writer is active on the same connection — the
    CLI path achieves this by SIGTERMing the scheduler daemon first. A
    future TUI caller (Task 3.3 WalletResetModal) needs to pause the poll
    job or accept that concurrent writes during the DELETEs are a live
    hazard.
    """
    if starting_balance <= 0:
        raise ValueError(
            f"starting_balance must be positive, got {starting_balance}"
        )
    now = datetime.now(UTC).isoformat()
    with db.conn:
        db.conn.execute("DELETE FROM positions")
        db.conn.execute("DELETE FROM wallet_transactions")
        db.conn.execute("DELETE FROM wallet")
        db.conn.execute(
            "INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) "
            "VALUES (1,?,?,0,0,?,?)",
            (starting_balance, starting_balance, now, now),
        )
