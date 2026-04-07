"""Paper trading: SQLite-backed trade marking, resolution, and stats via PolilyDB."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

DEFAULT_POSITION_SIZE = 20.0
DEFAULT_FRICTION_PCT = 0.04


@dataclass
class PaperTrade:
    id: str
    market_id: str
    title: str
    market_type: str | None
    side: str  # "yes" or "no"
    entry_price: float
    structure_score: float | None
    mispricing_signal: str | None
    status: str  # "open" or "resolved"
    resolved_result: str | None  # "yes" or "no"
    paper_pnl: float | None
    friction_adjusted_pnl: float | None
    scan_id: str | None
    marked_at: str
    resolved_at: str | None
    position_size_usd: float


class PaperTradingDB:
    """Paper trading store backed by PolilyDB's paper_trades table."""

    def __init__(
        self,
        db,
        position_size_usd: float = DEFAULT_POSITION_SIZE,
        friction_pct: float = DEFAULT_FRICTION_PCT,
    ):
        self.db = db
        self.position_size_usd = position_size_usd
        self.friction_pct = friction_pct

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass  # PolilyDB owns the connection, not us

    def mark(
        self,
        market_id: str,
        title: str,
        side: str,
        entry_price: float,
        market_type: str | None = None,
        structure_score: float | None = None,
        mispricing_signal: str | None = None,
        scan_id: str | None = None,
    ) -> PaperTrade:
        if side not in ("yes", "no"):
            raise ValueError(f"side must be 'yes' or 'no', got '{side}'")
        if entry_price <= 0:
            raise ValueError(f"entry_price must be positive, got {entry_price}")

        trade_id = f"pt_{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC).isoformat()

        self.db.conn.execute(
            """INSERT INTO paper_trades
               (id, market_id, title, market_type, side, entry_price,
                structure_score, mispricing_signal, scan_id, status, marked_at, position_size_usd)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?)""",
            (trade_id, market_id, title, market_type, side, entry_price,
             structure_score, mispricing_signal, scan_id, now, self.position_size_usd),
        )
        self.db.conn.commit()

        return PaperTrade(
            id=trade_id, market_id=market_id, title=title,
            market_type=market_type, side=side, entry_price=entry_price,
            structure_score=structure_score, mispricing_signal=mispricing_signal,
            scan_id=scan_id, status="open", resolved_result=None,
            paper_pnl=None, friction_adjusted_pnl=None,
            marked_at=now, resolved_at=None,
            position_size_usd=self.position_size_usd,
        )

    def resolve(self, trade_id: str, result: str) -> PaperTrade:
        trade = self.get(trade_id)
        if trade is None:
            raise ValueError(f"Trade {trade_id} not found")

        paper_pnl = self._calc_pnl(trade.side, trade.entry_price, result, trade.position_size_usd)
        friction_cost = trade.position_size_usd * self.friction_pct
        friction_adjusted_pnl = paper_pnl - friction_cost
        now = datetime.now(UTC).isoformat()

        self.db.conn.execute(
            """UPDATE paper_trades
               SET status='resolved', resolved_result=?, paper_pnl=?,
                   friction_adjusted_pnl=?, resolved_at=?
               WHERE id=?""",
            (result, paper_pnl, friction_adjusted_pnl, now, trade_id),
        )
        self.db.conn.commit()

        trade.status = "resolved"
        trade.resolved_result = result
        trade.paper_pnl = paper_pnl
        trade.friction_adjusted_pnl = friction_adjusted_pnl
        trade.resolved_at = now
        return trade

    def _calc_pnl(self, side: str, entry_price: float, result: str, position_size: float) -> float:
        shares = position_size / entry_price
        if side == "yes":
            payout_per_share = 1.0 if result == "yes" else 0.0
        else:
            payout_per_share = 1.0 if result == "no" else 0.0
        return shares * payout_per_share - position_size

    def get(self, trade_id: str) -> PaperTrade | None:
        row = self.db.conn.execute(
            "SELECT * FROM paper_trades WHERE id=?", (trade_id,),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_trade(row)

    def list_open(self) -> list[PaperTrade]:
        rows = self.db.conn.execute(
            "SELECT * FROM paper_trades WHERE status='open' ORDER BY marked_at DESC",
        ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def list_resolved(self) -> list[PaperTrade]:
        rows = self.db.conn.execute(
            "SELECT * FROM paper_trades WHERE status='resolved' ORDER BY resolved_at DESC",
        ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def list_all(self) -> list[PaperTrade]:
        rows = self.db.conn.execute(
            "SELECT * FROM paper_trades ORDER BY marked_at DESC",
        ).fetchall()
        return [self._row_to_trade(r) for r in rows]

    def weekly_stats(self) -> dict:
        return self.stats(days=7)

    def weekly_friction(self) -> float:
        cutoff = (datetime.now(UTC) - timedelta(days=7)).isoformat()
        rows = self.db.conn.execute(
            "SELECT entry_price, position_size_usd FROM paper_trades WHERE marked_at >= ?",
            (cutoff,),
        ).fetchall()
        return sum(r["position_size_usd"] * self.friction_pct for r in rows)

    def stats(self, days: int | None = None) -> dict:
        all_trades = self.list_all()
        if days is not None:
            cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
            all_trades = [t for t in all_trades if t.marked_at >= cutoff]
        resolved = [t for t in all_trades if t.status == "resolved"]
        open_trades = [t for t in all_trades if t.status == "open"]
        wins = [t for t in resolved if t.paper_pnl is not None and t.paper_pnl > 0]
        losses = [t for t in resolved if t.paper_pnl is not None and t.paper_pnl <= 0]

        total_paper_pnl = sum(t.paper_pnl for t in resolved if t.paper_pnl is not None)
        total_friction_adjusted = sum(
            t.friction_adjusted_pnl for t in resolved if t.friction_adjusted_pnl is not None
        )

        return {
            "total_trades": len(all_trades),
            "open": len(open_trades),
            "resolved": len(resolved),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(resolved) if resolved else 0.0,
            "total_paper_pnl": round(total_paper_pnl, 2),
            "total_friction_adjusted_pnl": round(total_friction_adjusted, 2),
        }

    def _row_to_trade(self, row) -> PaperTrade:
        return PaperTrade(
            id=row["id"],
            market_id=row["market_id"],
            title=row["title"],
            market_type=row["market_type"],
            side=row["side"],
            entry_price=row["entry_price"],
            structure_score=row["structure_score"],
            mispricing_signal=row["mispricing_signal"],
            scan_id=row["scan_id"],
            status=row["status"],
            resolved_result=row["resolved_result"],
            paper_pnl=row["paper_pnl"],
            friction_adjusted_pnl=row["friction_adjusted_pnl"],
            marked_at=row["marked_at"],
            resolved_at=row["resolved_at"],
            position_size_usd=row["position_size_usd"],
        )
