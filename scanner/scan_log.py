"""Scan log: persist scan execution metadata in SQLite."""

import json
import logging
from datetime import UTC, datetime

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class ScanStepRecord(BaseModel):
    """A single pipeline step's record."""

    name: str
    status: str  # done, skip, fail
    detail: str = ""
    elapsed: float = 0.0


class ScanLogEntry(BaseModel):
    """A single scan or analysis run's record."""

    scan_id: str  # matches archive filename, e.g. "20260329_145141"
    started_at: str  # ISO 8601
    finished_at: str | None = None
    total_elapsed: float = 0.0
    status: str = "running"  # running, completed, failed
    error: str | None = None

    type: str = "scan"  # "scan" or "analyze"
    event_id: str | None = None  # for analyze type
    market_title: str | None = None  # for analyze type

    total_markets: int = 0
    research_count: int = 0
    watchlist_count: int = 0
    filtered_count: int = 0

    steps: list[ScanStepRecord] = []


def save_scan_log(entry: ScanLogEntry, db) -> None:
    """Save a single scan log entry to SQLite."""
    steps_json = json.dumps(
        [s.model_dump() for s in entry.steps], ensure_ascii=False,
    ) if entry.steps else None
    db.conn.execute(
        """INSERT OR REPLACE INTO scan_logs
        (scan_id, type, event_id, market_title, started_at, finished_at,
         total_elapsed, status, error, total_markets,
         research_count, watchlist_count, filtered_count, steps)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            entry.scan_id, entry.type, entry.event_id, entry.market_title,
            entry.started_at, entry.finished_at,
            entry.total_elapsed, entry.status, entry.error,
            entry.total_markets, entry.research_count,
            entry.watchlist_count, entry.filtered_count, steps_json,
        ),
    )
    db.conn.commit()


def load_scan_logs(db, limit: int = 100) -> list[ScanLogEntry]:
    """Load scan logs from SQLite, most recent first."""
    rows = db.conn.execute(
        "SELECT * FROM scan_logs ORDER BY started_at DESC LIMIT ?", (limit,),
    ).fetchall()
    result = []
    for row in rows:
        try:
            steps_raw = json.loads(row["steps"]) if row["steps"] else []
            steps = [ScanStepRecord.model_validate(s) for s in steps_raw]
            result.append(ScanLogEntry(
                scan_id=row["scan_id"],
                type=row["type"],
                event_id=row["event_id"],
                market_title=row["market_title"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                total_elapsed=row["total_elapsed"],
                status=row["status"],
                error=row["error"],
                total_markets=row["total_markets"],
                research_count=row["research_count"],
                watchlist_count=row["watchlist_count"],
                filtered_count=row["filtered_count"],
                steps=steps,
            ))
        except Exception as e:
            logger.warning("Failed to parse scan log entry: %s", e)
    return result


def create_log_entry() -> ScanLogEntry:
    """Create a new running log entry with current timestamp."""
    now = datetime.now(UTC)
    return ScanLogEntry(
        scan_id=now.strftime("%Y%m%d_%H%M%S"),
        started_at=now.isoformat(),
        status="running",
    )


def finish_log_entry(
    entry: ScanLogEntry,
    status: str,
    steps: list[ScanStepRecord],
    total_markets: int = 0,
    research_count: int = 0,
    watchlist_count: int = 0,
    filtered_count: int = 0,
    error: str | None = None,
) -> ScanLogEntry:
    """Finalize a log entry with results."""
    now = datetime.now(UTC)
    entry.finished_at = now.isoformat()
    entry.status = status
    entry.error = error
    entry.steps = steps
    try:
        started = datetime.fromisoformat(entry.started_at)
        entry.total_elapsed = (now - started).total_seconds()
    except (ValueError, TypeError):
        entry.total_elapsed = sum(s.elapsed for s in steps)
    entry.total_markets = total_markets
    entry.research_count = research_count
    entry.watchlist_count = watchlist_count
    entry.filtered_count = filtered_count
    return entry
