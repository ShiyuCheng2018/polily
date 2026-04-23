"""PositionManager — maintains aggregated (market_id, side) positions.

Weighted-average cost basis on add. Realized P&L accumulates on reduce.
Row deleted when shares fully closed (float precision guard: <= 1e-9).

Atomicity contract: write methods take `commit: bool = True`. Default keeps
standalone usage transactional. TradeEngine passes `False` and wraps the
position mutation + wallet debit/credit in a single BEGIN/COMMIT. When
`commit=False`, the caller owns the open transaction and MUST call
`db.conn.rollback()` on any failure path — otherwise a subsequent
`commit=True` call will silently commit partial state.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polily.core.db import PolilyDB


_VALID_SIDES = ("yes", "no")
_SHARES_EPS = 1e-9  # Float precision guard for "fully closed" comparisons.

# Below this threshold, a position is "dust": the share count is too small to
# produce meaningful P&L (max value < $0.10 if the favorable outcome resolves,
# realistically a couple of cents). Partial sells often leave these behind due
# to floating-point arithmetic. Display layers (paper_status, wallet balance
# card, event_detail PositionPanel) filter dust out so the user isn't confused
# by 0.02-share stragglers. Accounting layers (trade_engine, narrator prompt,
# trade guard, monitor toggle) still see the raw row — dust is real state,
# just not worth surfacing.
DUST_SHARE_THRESHOLD = 0.1


def is_dust_position(position: dict) -> bool:
    """True when the position's share count is below the dust threshold."""
    try:
        return float(position["shares"]) < DUST_SHARE_THRESHOLD
    except (KeyError, TypeError, ValueError):
        return False


class PositionNotFound(Exception):  # noqa: N818  (plan-specified name; consistent with InsufficientFunds/InsufficientShares)
    """Raised when remove_shares is called on a non-existent position."""


class InsufficientShares(Exception):  # noqa: N818
    """Raised when remove_shares would drive share count below zero."""


class PositionManager:
    def __init__(self, db: PolilyDB) -> None:
        self.db = db

    # ---- reads ----
    def get_position(self, market_id: str, side: str) -> dict | None:
        row = self.db.conn.execute(
            "SELECT * FROM positions WHERE market_id=? AND side=?",
            (market_id, side),
        ).fetchone()
        return dict(row) if row else None

    def get_all_positions(self) -> list[dict]:
        cur = self.db.conn.execute(
            "SELECT * FROM positions ORDER BY opened_at DESC"
        )
        return [dict(r) for r in cur.fetchall()]

    def get_event_positions(self, event_id: str) -> list[dict]:
        cur = self.db.conn.execute(
            "SELECT * FROM positions WHERE event_id=? ORDER BY opened_at DESC",
            (event_id,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ---- writes ----
    def add_shares(
        self,
        *,
        market_id: str,
        side: str,
        event_id: str,
        title: str,
        shares: float,
        price: float,
        commit: bool = True,
    ) -> None:
        """Buy or add. Weighted-average avg_cost update.

        Caller owns rollback if commit=False.
        """
        if shares <= 0:
            raise ValueError(f"shares must be positive, got {shares}")
        if not 0 < price < 1:
            raise ValueError(f"price must be in (0, 1), got {price}")
        if side not in _VALID_SIDES:
            raise ValueError(f"side must be one of {_VALID_SIDES}, got {side!r}")

        now = datetime.now(UTC).isoformat()
        existing = self.get_position(market_id, side)
        if existing is None:
            cost_basis = shares * price
            self.db.conn.execute(
                """INSERT INTO positions
                (market_id,side,event_id,shares,avg_cost,cost_basis,realized_pnl,title,opened_at,updated_at)
                VALUES (?,?,?,?,?,?,0,?,?,?)""",
                (market_id, side, event_id, shares, price, cost_basis, title, now, now),
            )
        else:
            new_shares = existing["shares"] + shares
            new_avg = (
                existing["shares"] * existing["avg_cost"] + shares * price
            ) / new_shares
            new_cost_basis = new_shares * new_avg
            self.db.conn.execute(
                """UPDATE positions
                SET shares=?, avg_cost=?, cost_basis=?, updated_at=?
                WHERE market_id=? AND side=?""",
                (new_shares, new_avg, new_cost_basis, now, market_id, side),
            )
        if commit:
            self.db.conn.commit()

    def remove_shares(
        self,
        *,
        market_id: str,
        side: str,
        shares: float,
        price: float,
        commit: bool = True,
    ) -> float:
        """Sell or reduce. Returns realized P&L for this partial exit.

        Row is deleted when shares fully closed. Caller owns rollback if commit=False.

        price is intentionally not range-validated: exits at 0.0 or 1.0 are legal
        (post-resolution settlement path may hit extreme execution prices).
        """
        if shares <= 0:
            raise ValueError(f"shares must be positive, got {shares}")
        pos = self.get_position(market_id, side)
        if pos is None:
            raise PositionNotFound(f"{market_id}/{side}")
        if shares > pos["shares"]:
            raise InsufficientShares(
                f"requested {shares} > held {pos['shares']}"
            )

        realized = (price - pos["avg_cost"]) * shares
        new_shares = pos["shares"] - shares
        new_realized_total = pos["realized_pnl"] + realized
        now = datetime.now(UTC).isoformat()

        if new_shares <= _SHARES_EPS:  # fully closed (float precision guard)
            self.db.conn.execute(
                "DELETE FROM positions WHERE market_id=? AND side=?",
                (market_id, side),
            )
        else:
            new_cost_basis = new_shares * pos["avg_cost"]
            self.db.conn.execute(
                """UPDATE positions
                SET shares=?, cost_basis=?, realized_pnl=?, updated_at=?
                WHERE market_id=? AND side=?""",
                (new_shares, new_cost_basis, new_realized_total, now, market_id, side),
            )
        if commit:
            self.db.conn.commit()

        return realized
