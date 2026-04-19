"""TradeEngine — orchestrates WalletService + PositionManager for buy/sell.

Atomicity: every execute_buy / execute_sell is a single DB transaction. The
cash debit, fee debit (if any), and position mutation all succeed or all roll
back. WalletService and PositionManager write methods are called with
`commit=False`; this class owns the outer BEGIN / COMMIT / rollback.

Autopilot seam: v0.7+ live execution replaces `_fetch_live_price` with a real
order call. Everything else stays.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from scanner.core.fees import calculate_taker_fee
from scanner.core.positions import InsufficientShares
from scanner.core.wallet import InsufficientFunds

if TYPE_CHECKING:
    from scanner.core.db import PolilyDB
    from scanner.core.positions import PositionManager
    from scanner.core.wallet import WalletService

logger = logging.getLogger(__name__)

CLOB_PRICE_URL = "https://clob.polymarket.com/price"
_HTTP_TIMEOUT = 2.0


class TradeEngine:
    def __init__(
        self,
        db: PolilyDB,
        wallet: WalletService,
        positions: PositionManager,
    ) -> None:
        self.db = db
        self.wallet = wallet
        self.positions = positions

    # ---- public ops ----
    def execute_buy(self, *, market_id: str, side: str, shares: float) -> dict:
        """Buy `shares` of `side` at live price. Atomic: all writes commit together."""
        if side not in ("yes", "no"):
            raise ValueError(f"side must be yes/no, got {side!r}")
        if shares <= 0:
            raise ValueError(f"shares must be positive, got {shares}")
        market, event = self._load_market_event(market_id)
        price = self._fetch_live_price(market, side, buy_side=True)
        if not 0 < price < 1:
            raise ValueError(
                f"price {price} out of range (0, 1) — market may be near-resolved, refusing trade"
            )
        cost = shares * price
        fee = calculate_taker_fee(
            shares=shares, price=price,
            fees_enabled=bool(market.get("fees_enabled")),
            fee_rate=market.get("fee_rate"),
        )

        # Advisory pre-check before BEGIN — fail fast without a rollback round-trip.
        # The authoritative check lives inside wallet.deduct, which re-reads cash under
        # the transaction and raises InsufficientFunds if the balance shifted.
        if self.wallet.get_cash() < cost + fee:
            raise InsufficientFunds(
                f"need ${cost + fee:.4f} (cost ${cost:.4f} + fee ${fee:.4f}), "
                f"have ${self.wallet.get_cash():.2f}"
            )

        # All prior calls are read-only; safe to open an explicit BEGIN here.
        self._atomic_buy(
            market_id=market_id,
            side=side,
            shares=shares,
            price=price,
            cost=cost,
            fee=fee,
            event_id=event["event_id"],
            title=market["question"][:40],
        )
        return {"price": price, "cost": cost, "fee": fee}

    def _atomic_buy(
        self,
        *,
        market_id: str,
        side: str,
        shares: float,
        price: float,
        cost: float,
        fee: float,
        event_id: str,
        title: str,
    ) -> None:
        """Inner BUY transaction. Uses try/finally + flag so commit failures AND
        BaseException (KeyboardInterrupt) both trigger rollback — the shared
        check_same_thread=False connection makes leaked transactions process-wide.
        """
        committed = False
        self.db.conn.execute("BEGIN")
        try:
            self.wallet.deduct(
                cost,
                tx_type="BUY",
                commit=False,
                market_id=market_id,
                event_id=event_id,
                side=side,
                shares=shares,
                price=price,
            )
            if fee > 0:
                self.wallet.deduct(
                    fee,
                    tx_type="FEE",
                    commit=False,
                    market_id=market_id,
                    event_id=event_id,
                    side=side,
                    notes=f"taker fee for BUY {shares}@{price}",
                )
            self.positions.add_shares(
                market_id=market_id,
                side=side,
                event_id=event_id,
                title=title,
                shares=shares,
                price=price,
                commit=False,
            )
            self.db.conn.commit()
            committed = True
        finally:
            if not committed:
                try:
                    self.db.conn.rollback()
                except Exception:
                    logger.exception("rollback after BUY failure also failed")

    def execute_sell(self, *, market_id: str, side: str, shares: float) -> dict:
        """Sell `shares` of `side` at live price. Atomic: all writes commit together."""
        if side not in ("yes", "no"):
            raise ValueError(f"side must be yes/no, got {side!r}")
        if shares <= 0:
            raise ValueError(f"shares must be positive, got {shares}")
        market, event = self._load_market_event(market_id)
        price = self._fetch_live_price(market, side, buy_side=False)
        if not 0 < price < 1:
            raise ValueError(
                f"price {price} out of range (0, 1) — market may be near-resolved, refusing trade"
            )
        proceeds = shares * price
        fee = calculate_taker_fee(
            shares=shares, price=price,
            fees_enabled=bool(market.get("fees_enabled")),
            fee_rate=market.get("fee_rate"),
        )

        # Advisory pre-check before BEGIN. remove_shares re-validates under the
        # transaction, so this is fail-fast only.
        pos = self.positions.get_position(market_id, side)
        held = pos["shares"] if pos else 0
        if pos is None or pos["shares"] < shares:
            raise InsufficientShares(f"requested {shares} > held {held}")

        realized = self._atomic_sell(
            market_id=market_id,
            side=side,
            shares=shares,
            price=price,
            proceeds=proceeds,
            fee=fee,
            event_id=event["event_id"],
        )
        return {
            "price": price,
            "proceeds": proceeds,
            "fee": fee,
            "realized_pnl": realized,
        }

    def _atomic_sell(
        self,
        *,
        market_id: str,
        side: str,
        shares: float,
        price: float,
        proceeds: float,
        fee: float,
        event_id: str,
    ) -> float:
        """Inner SELL transaction. Same try/finally + flag pattern as BUY."""
        committed = False
        realized: float = 0.0
        self.db.conn.execute("BEGIN")
        try:
            realized = self.positions.remove_shares(
                market_id=market_id,
                side=side,
                shares=shares,
                price=price,
                commit=False,
            )
            self.wallet.credit(
                proceeds,
                tx_type="SELL",
                commit=False,
                market_id=market_id,
                event_id=event_id,
                side=side,
                shares=shares,
                price=price,
                realized_pnl=realized,
            )
            if fee > 0:
                self.wallet.deduct(
                    fee,
                    tx_type="FEE",
                    commit=False,
                    market_id=market_id,
                    event_id=event_id,
                    side=side,
                    notes=f"taker fee for SELL {shares}@{price}",
                )
            self.db.conn.commit()
            committed = True
        finally:
            if not committed:
                try:
                    self.db.conn.rollback()
                except Exception:
                    logger.exception("rollback after SELL failure also failed")
        return realized

    # ---- internals ----
    def _load_market_event(self, market_id: str) -> tuple[dict, dict]:
        m = self.db.conn.execute(
            "SELECT * FROM markets WHERE market_id=?", (market_id,)
        ).fetchone()
        if m is None:
            raise ValueError(f"market {market_id} not found")
        e = self.db.conn.execute(
            "SELECT * FROM events WHERE event_id=?", (m["event_id"],)
        ).fetchone()
        if e is None:
            # Orphaned market — cascade delete race or seed corruption. Fail loudly
            # rather than let a KeyError on event["event_id"] mask the real cause.
            raise ValueError(
                f"event {m['event_id']} not found for market {market_id}"
            )
        return dict(m), dict(e)

    def _fetch_live_price(self, market: dict, side: str, buy_side: bool) -> float:
        """Return the execution price for `side` given buy/sell direction.

        Buy yes  → pay ask  (CLOB side=SELL on yes token).
        Sell yes → hit bid  (CLOB side=BUY on yes token).
        NO is the complement: price_no = 1 - price_yes_opposite.

        Falls back to DB `yes_price` (or its complement for NO) on HTTP failure
        or when the market lacks a clob_token_id_yes.
        """
        token_yes = market.get("clob_token_id_yes")
        db_yes = market.get("yes_price") or 0.5

        if not token_yes:
            return db_yes if side == "yes" else round(1 - db_yes, 4)

        if side == "yes":
            api_side = "SELL" if buy_side else "BUY"
            fallback = db_yes
        else:
            # NO buy = complement of yes bid; NO sell = complement of yes ask.
            api_side = "BUY" if buy_side else "SELL"
            fallback = round(1 - db_yes, 4)

        try:
            r = httpx.get(
                CLOB_PRICE_URL,
                params={"token_id": token_yes, "side": api_side},
                timeout=_HTTP_TIMEOUT,
            )
            if r.status_code != 200:
                return fallback
            yes_side_price = float(r.json()["price"])
            return yes_side_price if side == "yes" else round(1 - yes_side_price, 4)
        except Exception:
            logger.warning(
                "_fetch_live_price failed, fallback to DB yes_price", exc_info=True
            )
            return fallback
