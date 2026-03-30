"""Scan log: persist scan execution metadata (timing, steps, results)."""

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel


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
    market_id: str | None = None  # for analyze type
    market_title: str | None = None  # for analyze type

    total_markets: int = 0
    research_count: int = 0
    watchlist_count: int = 0
    filtered_count: int = 0

    steps: list[ScanStepRecord] = []


def load_scan_logs(path: str | Path) -> list[ScanLogEntry]:
    """Load scan logs from JSON file."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        with open(p) as f:
            data = json.load(f)
        return [ScanLogEntry.model_validate(entry) for entry in data]
    except (json.JSONDecodeError, ValueError):
        return []


def save_scan_logs(logs: list[ScanLogEntry], path: str | Path, max_entries: int = 30):
    """Save scan logs to JSON file, truncating to max_entries."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    trimmed = logs[-max_entries:]
    with open(p, "w") as f:
        json.dump([entry.model_dump() for entry in trimmed], f, indent=2, ensure_ascii=False)


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
    # Wall clock time from start to finish
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
