"""ResolutionHandler — settles resolved markets against user positions.

Wired in from `scanner.daemon.poll_job` once a market transitions to closed
and the user has live positions on it (Task 2.2).

Design notes:
- `derive_winner` uses a >=0.99 threshold instead of exact "1" / "0" string
  match because Gamma inconsistently encodes outcomePrices as "1", "1.0",
  "1.00", or "0.995" during the pre-settlement oracle window.
- Per-position settlement: YES holders collect at `payout_per_share = 1.0`
  if YES wins, `0.0` if NO wins. Split payout is `0.5` for both sides.
- `markets.resolved_outcome` is persisted even when the user held no
  positions — keeps the DB authoritative for replay / dashboards.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB
    from scanner.core.positions import PositionManager
    from scanner.core.wallet import WalletService

logger = logging.getLogger(__name__)

_VALID_WINNERS = ("yes", "no", "split")
_WIN_THRESHOLD = 0.99
_LOSS_THRESHOLD = 0.01
_SPLIT_TOLERANCE = 0.01


def derive_winner(outcome_prices: list[str]) -> str | None:
    """Given Gamma `outcomePrices` list, return 'yes' / 'no' / 'split' / None.

    Float-threshold comparison defends against Gamma's inconsistent string
    encodings ("1" vs "1.0" vs "1.00"). Returns None for unresolved, in-
    progress disputes, and malformed input.
    """
    if len(outcome_prices) != 2:
        return None
    try:
        a, b = float(outcome_prices[0]), float(outcome_prices[1])
    except (ValueError, TypeError):
        return None
    if a >= _WIN_THRESHOLD and b <= _LOSS_THRESHOLD:
        return "yes"
    if b >= _WIN_THRESHOLD and a <= _LOSS_THRESHOLD:
        return "no"
    if abs(a - 0.5) < _SPLIT_TOLERANCE and abs(b - 0.5) < _SPLIT_TOLERANCE:
        return "split"
    return None


class ResolutionHandler:
    def __init__(
        self,
        db: PolilyDB,
        wallet: WalletService,
        positions: PositionManager,
    ) -> None:
        self.db = db
        self.wallet = wallet
        self.positions = positions

    def resolve_market(
        self, market_id: str, winner_side: str,
    ) -> tuple[int, float]:
        """Settle every position on `market_id` against `winner_side`.

        winner_side: 'yes' | 'no' | 'split'. Callers should skip when
        `derive_winner` returned None (market still disputing) — this method
        will ValueError on any other input.

        Returns (positions_settled, credited_total_usd). A no-op call (no
        positions) returns (0, 0.0) so callers can suppress log noise.

        Atomicity: the entire settlement (markets.resolved_outcome UPDATE +
        every position's credit + DELETE) runs in a single transaction. A
        crash mid-iteration rolls back all of it, so retrying on the next
        poll tick cannot double-credit. `wallet.credit(commit=False)` defers
        to this outer transaction's commit.
        """
        if winner_side not in _VALID_WINNERS:
            raise ValueError(
                f"winner_side must be one of {_VALID_WINNERS}, got {winner_side!r}"
            )

        with self.db.conn:
            cur = self.db.conn.execute(
                "UPDATE markets SET resolved_outcome=? WHERE market_id=?",
                (winner_side, market_id),
            )
            if cur.rowcount == 0:
                logger.warning(
                    "resolve_market: no market row for %s; outcome not persisted",
                    market_id,
                )

            rows = self.db.conn.execute(
                "SELECT * FROM positions WHERE market_id=?", (market_id,)
            ).fetchall()

            credited_total = 0.0
            for r in rows:
                pos = dict(r)
                payout_per_share = _payout_per_share(winner_side, pos["side"])
                proceeds = pos["shares"] * payout_per_share
                realized = proceeds - pos["cost_basis"]

                self.wallet.credit(
                    proceeds,
                    tx_type="RESOLVE",
                    commit=False,
                    market_id=market_id,
                    event_id=pos["event_id"],
                    side=pos["side"],
                    shares=pos["shares"],
                    price=payout_per_share,
                    realized_pnl=realized,
                    notes=_resolve_notes(winner_side),
                )
                self.db.conn.execute(
                    "DELETE FROM positions WHERE market_id=? AND side=?",
                    (market_id, pos["side"]),
                )
                credited_total += proceeds

            if rows:
                logger.info(
                    "resolved %s -> %s, settled %d positions, credited $%.2f",
                    market_id, winner_side, len(rows), credited_total,
                )
            return len(rows), credited_total


def _payout_per_share(winner_side: str, position_side: str) -> float:
    if winner_side == "split":
        return 0.5
    return 1.0 if winner_side == position_side else 0.0


def _resolve_notes(winner_side: str) -> str:
    return {"yes": "YES won", "no": "NO won", "split": "split (50/50)"}[winner_side]
