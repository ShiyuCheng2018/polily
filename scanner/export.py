"""Export: paper trades to CSV using PolilyDB."""

import csv
import logging

logger = logging.getLogger(__name__)

TRADE_COLUMNS = [
    "id", "event_id", "market_id", "title", "side", "entry_price",
    "position_size_usd", "structure_score", "mispricing_signal", "scan_id",
    "status", "resolved_result", "paper_pnl", "friction_adjusted_pnl",
    "marked_at", "resolved_at",
]


def export_trades_csv(db, output_path: str) -> int:
    """Export all paper trades to CSV, joined with market/event data.

    Returns the number of rows written.
    """
    cur = db.conn.execute(
        """
        SELECT
            pt.id, pt.event_id, pt.market_id, pt.title, pt.side,
            pt.entry_price, pt.position_size_usd, pt.structure_score,
            pt.mispricing_signal, pt.scan_id, pt.status,
            pt.resolved_result, pt.paper_pnl, pt.friction_adjusted_pnl,
            pt.marked_at, pt.resolved_at,
            e.title AS event_title, e.market_type,
            m.yes_price, m.no_price
        FROM paper_trades pt
        LEFT JOIN events e ON pt.event_id = e.event_id
        LEFT JOIN markets m ON pt.market_id = m.market_id
        ORDER BY pt.marked_at DESC
        """,
    )
    rows = [dict(row) for row in cur.fetchall()]

    all_columns = TRADE_COLUMNS + ["event_title", "market_type", "yes_price", "no_price"]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=all_columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col) for col in all_columns})

    logger.info("Exported %d paper trades to %s", len(rows), output_path)
    return len(rows)
