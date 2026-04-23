"""Analysis store: persist per-event AI analysis versions in SQLite."""

import json
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnalysisVersion(BaseModel):
    """A single AI analysis snapshot for an event."""

    version: int  # 1-indexed
    created_at: str  # ISO 8601

    # Trigger metadata
    trigger_source: str = "manual"  # manual / scan / scheduled / movement

    # Prices at analysis time (JSON dict of sub-market prices)
    prices_snapshot: dict = {}

    # Agent outputs (stored as JSON TEXT in SQLite)
    narrative_output: dict = {}

    # Score snapshot
    structure_score: float | None = None
    score_breakdown: dict | None = None

    # Mispricing
    mispricing_signal: str = "none"
    mispricing_details: str | None = None

    # Metadata
    elapsed_seconds: float = 0.0


def append_analysis(event_id: str, version: AnalysisVersion, db) -> None:
    """Append an analysis version for an event. No version limit."""
    db.conn.execute(
        """INSERT INTO analyses
        (event_id, version, created_at, trigger_source,
         prices_snapshot, narrative_output,
         structure_score, score_breakdown,
         mispricing_signal, mispricing_details, elapsed_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            event_id, version.version, version.created_at,
            version.trigger_source,
            json.dumps(version.prices_snapshot, ensure_ascii=False),
            json.dumps(version.narrative_output, ensure_ascii=False),
            version.structure_score,
            json.dumps(version.score_breakdown, ensure_ascii=False) if version.score_breakdown else None,
            version.mispricing_signal, version.mispricing_details,
            version.elapsed_seconds,
        ),
    )
    db.conn.commit()


def get_event_analyses(event_id: str, db) -> list[AnalysisVersion]:
    """Get all analysis versions for an event, ordered by version."""
    rows = db.conn.execute(
        "SELECT * FROM analyses WHERE event_id = ? ORDER BY version ASC",
        (event_id,),
    ).fetchall()
    result = []
    for row in rows:
        try:
            result.append(_row_to_version(row))
        except Exception as e:
            logger.warning("Failed to parse analysis version: %s", e)
    return result


def _row_to_version(row) -> AnalysisVersion:
    return AnalysisVersion(
        version=row["version"],
        created_at=row["created_at"],
        trigger_source=row["trigger_source"],
        prices_snapshot=json.loads(row["prices_snapshot"]) if row["prices_snapshot"] else {},
        narrative_output=json.loads(row["narrative_output"]) if row["narrative_output"] else {},
        structure_score=row["structure_score"],
        score_breakdown=json.loads(row["score_breakdown"]) if row["score_breakdown"] else None,
        mispricing_signal=row["mispricing_signal"],
        mispricing_details=row["mispricing_details"],
        elapsed_seconds=row["elapsed_seconds"],
    )
