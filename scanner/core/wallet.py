"""WalletService — manages cash balance and the wallet_transactions ledger.

Invariant: every cash change is recorded. Never mutate `wallet.cash_usd` without
also inserting a wallet_transactions row in the same transaction.

Atomicity contract: write methods take `commit: bool = True`. Default keeps
standalone usage transactional. TradeEngine passes `False` and wraps multiple
calls in its own BEGIN/COMMIT.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB


class InsufficientFunds(Exception):  # noqa: N818  (short name matches plan convention)
    """Raised when a debit would push cash below zero."""


class WalletService:
    def __init__(self, db: PolilyDB) -> None:
        self.db = db

    # ---- initialization ----
    def initialize(self, starting_balance: float) -> None:
        """Create wallet singleton if not exists. Idempotent."""
        row = self.db.conn.execute("SELECT id FROM wallet WHERE id=1").fetchone()
        if row is not None:
            return
        now = datetime.now(UTC).isoformat()
        self.db.conn.execute(
            "INSERT INTO wallet (id,cash_usd,starting_balance,topup_total,withdraw_total,created_at,updated_at) "
            "VALUES (1,?,?,0,0,?,?)",
            (starting_balance, starting_balance, now, now),
        )
        self.db.conn.commit()

    # ---- reads ----
    def get_cash(self) -> float:
        row = self.db.conn.execute("SELECT cash_usd FROM wallet WHERE id=1").fetchone()
        return row["cash_usd"] if row else 0.0

    def get_starting_balance(self) -> float:
        row = self.db.conn.execute(
            "SELECT starting_balance FROM wallet WHERE id=1"
        ).fetchone()
        return row["starting_balance"] if row else 0.0

    def get_snapshot(self) -> dict:
        row = self.db.conn.execute("SELECT * FROM wallet WHERE id=1").fetchone()
        return dict(row) if row else {}

    def get_equity(self, positions_market_value: float) -> float:
        return self.get_cash() + positions_market_value

    def list_transactions(
        self, limit: int = 50, tx_type: str | None = None
    ) -> list[dict]:
        if tx_type:
            cur = self.db.conn.execute(
                "SELECT * FROM wallet_transactions WHERE type=? ORDER BY id DESC LIMIT ?",
                (tx_type, limit),
            )
        else:
            cur = self.db.conn.execute(
                "SELECT * FROM wallet_transactions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]

    # ---- writes ----
    def topup(
        self, amount: float, *, commit: bool = True, notes: str | None = None
    ) -> None:
        assert amount > 0, "topup amount must be positive"
        now = datetime.now(UTC).isoformat()
        self.db.conn.execute(
            "UPDATE wallet SET cash_usd=cash_usd+?, topup_total=topup_total+?, updated_at=? WHERE id=1",
            (amount, amount, now),
        )
        new_cash = self.get_cash()
        self._insert_tx("TOPUP", amount_usd=amount, balance_after=new_cash, notes=notes)
        if commit:
            self.db.conn.commit()

    def withdraw(self, amount: float, *, commit: bool = True) -> None:
        assert amount > 0, "withdraw amount must be positive"
        cash = self.get_cash()
        if amount > cash:
            raise InsufficientFunds(f"withdraw ${amount} exceeds cash ${cash}")
        now = datetime.now(UTC).isoformat()
        self.db.conn.execute(
            "UPDATE wallet SET cash_usd=cash_usd-?, withdraw_total=withdraw_total+?, updated_at=? WHERE id=1",
            (amount, amount, now),
        )
        new_cash = self.get_cash()
        self._insert_tx("WITHDRAW", amount_usd=-amount, balance_after=new_cash)
        if commit:
            self.db.conn.commit()

    def deduct(
        self, amount: float, *, tx_type: str, commit: bool = True, **tx_fields
    ) -> None:
        """Used for BUY and FEE. Raises InsufficientFunds before any write."""
        assert amount > 0
        assert tx_type in ("BUY", "FEE")
        cash = self.get_cash()
        if amount > cash:
            raise InsufficientFunds(f"deduct ${amount} exceeds cash ${cash}")
        now = datetime.now(UTC).isoformat()
        self.db.conn.execute(
            "UPDATE wallet SET cash_usd=cash_usd-?, updated_at=? WHERE id=1",
            (amount, now),
        )
        new_cash = self.get_cash()
        self._insert_tx(
            tx_type, amount_usd=-amount, balance_after=new_cash, **tx_fields
        )
        if commit:
            self.db.conn.commit()

    def credit(
        self, amount: float, *, tx_type: str, commit: bool = True, **tx_fields
    ) -> None:
        """Used for SELL and RESOLVE."""
        assert amount >= 0
        assert tx_type in ("SELL", "RESOLVE")
        now = datetime.now(UTC).isoformat()
        self.db.conn.execute(
            "UPDATE wallet SET cash_usd=cash_usd+?, updated_at=? WHERE id=1",
            (amount, now),
        )
        new_cash = self.get_cash()
        self._insert_tx(
            tx_type, amount_usd=amount, balance_after=new_cash, **tx_fields
        )
        if commit:
            self.db.conn.commit()

    # ---- internal ----
    def _insert_tx(
        self,
        tx_type: str,
        *,
        amount_usd: float,
        balance_after: float,
        fee_usd: float = 0.0,
        **fields,
    ) -> None:
        now = datetime.now(UTC).isoformat()
        self.db.conn.execute(
            """INSERT INTO wallet_transactions
            (created_at,type,market_id,event_id,side,shares,price,amount_usd,fee_usd,balance_after,realized_pnl,notes)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now,
                tx_type,
                fields.get("market_id"),
                fields.get("event_id"),
                fields.get("side"),
                fields.get("shares"),
                fields.get("price"),
                amount_usd,
                fee_usd,
                balance_after,
                fields.get("realized_pnl"),
                fields.get("notes"),
            ),
        )
