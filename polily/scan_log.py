"""Scan log: persist scan execution metadata in SQLite."""

import contextlib
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
    status: str = "running"  # pending | running | completed | failed | cancelled | superseded
    error: str | None = None

    type: str = "scan"  # "scan" or "analyze"
    event_id: str | None = None  # for analyze type
    market_title: str | None = None  # for analyze type

    total_markets: int = 0
    research_count: int = 0
    watchlist_count: int = 0
    filtered_count: int = 0

    steps: list[ScanStepRecord] = []

    # v0.7.0 scheduler fields
    scheduled_at: str | None = None
    trigger_source: str = "manual"  # manual | scan | scheduled | movement
    scheduled_reason: str | None = None


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
                scheduled_at=row["scheduled_at"],
                trigger_source=row["trigger_source"],
                scheduled_reason=row["scheduled_reason"],
            ))
        except Exception as e:
            logger.warning("Failed to parse scan log entry: %s", e)
    return result


def create_log_entry(log_type: str = "analyze") -> ScanLogEntry:
    """Create a new running log entry with current timestamp.

    Default is "analyze" since that's the common path; "add_event"
    caller overrides explicitly (URL-paste evaluation flow). The legacy
    "scan" value stays in the DB CHECK constraint for back-compat but
    no code path produces it.
    """
    now = datetime.now(UTC)
    return ScanLogEntry(
        scan_id=now.strftime("%Y%m%d_%H%M%S"),
        started_at=now.isoformat(),
        status="running",
        type=log_type,
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


# ---------------------------------------------------------------------------
# v0.7.0 lifecycle helpers — pending / running / superseded / cancelled
# ---------------------------------------------------------------------------

def _make_scan_id(prefix: str = "s") -> str:
    """Generate a scan_id unique to the second. Caller ensures no collisions."""
    import uuid
    now = datetime.now(UTC)
    return f"{prefix}_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"


def insert_pending_scan(
    *,
    event_id: str,
    event_title: str | None,
    scheduled_at: str,
    trigger_source: str,
    scheduled_reason: str | None,
    db,
) -> str:
    """Insert a pending scan row. Returns the new scan_id.

    Use trigger_source in ('scheduled','movement','manual') — validated by CHECK.
    """
    now = datetime.now(UTC).isoformat()
    scan_id = _make_scan_id(prefix="p")
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, market_title, started_at, "
        "status, trigger_source, scheduled_at, scheduled_reason) "
        "VALUES (?, 'analyze', ?, ?, ?, 'pending', ?, ?, ?)",
        (scan_id, event_id, event_title, now, trigger_source, scheduled_at, scheduled_reason),
    )
    db.conn.commit()
    return scan_id


def claim_pending_scan(scan_id: str, db) -> bool:
    """Atomically move a pending row to running. Returns False if already claimed."""
    now = datetime.now(UTC).isoformat()
    cur = db.conn.execute(
        "UPDATE scan_logs SET status='running', started_at=? "
        "WHERE scan_id=? AND status='pending'",
        (now, scan_id),
    )
    db.conn.commit()
    return cur.rowcount > 0


def finish_scan(
    scan_id: str,
    *,
    status: str,  # 'completed' | 'failed' | 'cancelled'
    error: str | None = None,
    db,
) -> int:
    """Finalize a running scan. Computes total_elapsed from started_at.

    Only transitions rows that are still `status='running'` — prevents a late
    narrator completion from overwriting a user's cancel, or a retry from
    stomping an already-finalized row. Returns rowcount (1 on success, 0 when
    the row was already in a terminal state).
    """
    if status not in ("completed", "failed", "cancelled"):
        raise ValueError(f"Invalid terminal status: {status!r}")
    now = datetime.now(UTC)
    started_row = db.conn.execute(
        "SELECT started_at FROM scan_logs WHERE scan_id=?", (scan_id,),
    ).fetchone()
    elapsed = 0.0
    if started_row and started_row["started_at"]:
        with contextlib.suppress(ValueError):
            elapsed = (now - datetime.fromisoformat(started_row["started_at"])).total_seconds()
    cur = db.conn.execute(
        "UPDATE scan_logs SET status=?, finished_at=?, total_elapsed=?, error=? "
        "WHERE scan_id=? AND status='running'",
        (status, now.isoformat(), elapsed, error, scan_id),
    )
    db.conn.commit()
    return cur.rowcount


def supersede_pending_for_event(event_id: str, db) -> int:
    """Mark every pending row for an event as superseded. Returns # rows changed."""
    cur = db.conn.execute(
        "UPDATE scan_logs SET status='superseded' "
        "WHERE event_id=? AND status='pending'",
        (event_id,),
    )
    db.conn.commit()
    return cur.rowcount


def fetch_overdue_pending(db) -> list[dict]:
    """Return AT MOST ONE overdue pending row per event — the earliest.

    Why one-per-event: Q1 requires we don't dispatch while a row is running;
    with multiple stale overdue rows for the same event (e.g. after Mac
    sleep), claiming them all in a single tick would spawn multiple agents
    for the same event. Picking the earliest per event (and relying on
    supersede on completion) keeps the invariant "at most one active
    analysis per event" true.

    The per-iteration claim_pending_scan atomic check is still required as
    a second line of defense against cross-tick races.
    """
    now = datetime.now(UTC).isoformat()
    rows = db.conn.execute(
        """
        WITH earliest_per_event AS (
            SELECT event_id, MIN(scheduled_at) AS min_sched
            FROM scan_logs
            WHERE status = 'pending' AND scheduled_at <= ?
            GROUP BY event_id
        )
        SELECT s.scan_id, s.event_id, s.market_title, s.scheduled_at,
               s.scheduled_reason, s.trigger_source
        FROM scan_logs s
        JOIN earliest_per_event e
          ON e.event_id = s.event_id AND e.min_sched = s.scheduled_at
        WHERE s.status = 'pending'
          AND NOT EXISTS (
              SELECT 1 FROM scan_logs s2
              WHERE s2.event_id = s.event_id AND s2.status = 'running'
          )
        ORDER BY s.scheduled_at ASC
        """,
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def fail_orphan_running(db) -> int:
    """On daemon startup, mark all rows stuck in 'running' as 'failed'.

    Q2 decision: no auto-retry. User sees failed row and decides manually.
    Returns count of rows updated.
    """
    now = datetime.now(UTC).isoformat()
    cur = db.conn.execute(
        "UPDATE scan_logs SET status='failed', finished_at=?, "
        "error='进程中断，未完成' "
        "WHERE status='running'",
        (now,),
    )
    db.conn.commit()
    return cur.rowcount
