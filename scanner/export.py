"""Export: paper trades and scan data to CSV."""

import csv
import json
import logging
from pathlib import Path

from scanner.paper_trading import PaperTradingDB

logger = logging.getLogger(__name__)

TRADE_COLUMNS = [
    "id", "market_id", "title", "market_type", "side", "entry_price",
    "structure_score", "mispricing_signal", "scan_id",
    "status", "resolved_result", "paper_pnl", "friction_adjusted_pnl",
    "marked_at", "resolved_at", "position_size_usd",
]

SCAN_COLUMNS = [
    "market_id", "title", "market_type", "tier",
    "yes_price", "no_price", "spread_pct_yes", "round_trip_friction_pct",
    "volume", "days_to_resolution", "structure_score",
    "mispricing_signal", "mispricing_direction", "theoretical_fair_value",
]


def export_trades_csv(db: PaperTradingDB, output_path: str):
    """Export all paper trades to CSV."""
    trades = db.list_all()
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=TRADE_COLUMNS)
        writer.writeheader()
        for t in trades:
            row = {}
            for col in TRADE_COLUMNS:
                row[col] = getattr(t, col, None)
            writer.writerow(row)


def export_scans_csv(scans_dir: str, output_path: str):
    """Export all scan archives to a single CSV (deduped by market_id, latest scan wins)."""
    scans_path = Path(scans_dir)
    if not scans_path.exists():
        # Write empty CSV with headers
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=SCAN_COLUMNS)
            writer.writeheader()
        return

    # Collect all entries, latest scan wins per market_id
    seen: dict[str, dict] = {}
    for path in sorted(scans_path.glob("*.json")):
        try:
            with open(path) as f:
                data = json.load(f)
            for entry in data:
                mid = entry.get("market_id")
                if mid:
                    seen[mid] = entry  # latest overwrites
        except (json.JSONDecodeError, OSError):
            continue

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=SCAN_COLUMNS)
        writer.writeheader()
        for entry in seen.values():
            row = {col: entry.get(col) for col in SCAN_COLUMNS}
            writer.writerow(row)
