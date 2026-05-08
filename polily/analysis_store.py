"""Analysis store: persist per-event AI analysis versions in SQLite."""

import json
import logging
from typing import Literal

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

    # Agent outputs (stored as TEXT in SQLite)
    # v0.12.0: narrative_output is dict for legacy ('json') rows or raw markdown
    # text including frontmatter for new ('markdown') rows. Caller dispatches
    # on narrative_format.
    narrative_output: dict | str = {}
    narrative_format: Literal["json", "markdown"] = "json"

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
    # Serialize narrative_output: dict → json string; str → as-is
    if isinstance(version.narrative_output, dict):
        narrative_serialized = json.dumps(version.narrative_output, ensure_ascii=False)
    else:
        narrative_serialized = version.narrative_output  # raw markdown text

    with db.transaction() as conn:
        conn.execute(
            """INSERT INTO analyses
            (event_id, version, created_at, trigger_source,
             prices_snapshot, narrative_output, narrative_format,
             structure_score, score_breakdown,
             mispricing_signal, mispricing_details, elapsed_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id, version.version, version.created_at,
                version.trigger_source,
                json.dumps(version.prices_snapshot, ensure_ascii=False),
                narrative_serialized,
                version.narrative_format,
                version.structure_score,
                json.dumps(version.score_breakdown, ensure_ascii=False) if version.score_breakdown else None,
                version.mispricing_signal, version.mispricing_details,
                version.elapsed_seconds,
            ),
        )


def get_event_analyses(event_id: str, db) -> list[AnalysisVersion]:
    """Get all analysis versions for an event, ordered by version."""
    with db.transaction() as conn:
        rows = conn.execute(
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
    fmt = row["narrative_format"]
    narrative_output: dict | str
    if fmt == "markdown":
        narrative_output = row["narrative_output"] or ""
    else:  # 'json' or any legacy / unrecognized value
        narrative_output = json.loads(row["narrative_output"]) if row["narrative_output"] else {}

    return AnalysisVersion(
        version=row["version"],
        created_at=row["created_at"],
        trigger_source=row["trigger_source"],
        prices_snapshot=json.loads(row["prices_snapshot"]) if row["prices_snapshot"] else {},
        narrative_output=narrative_output,
        narrative_format=fmt,
        structure_score=row["structure_score"],
        score_breakdown=json.loads(row["score_breakdown"]) if row["score_breakdown"] else None,
        mispricing_signal=row["mispricing_signal"],
        mispricing_details=row["mispricing_details"],
        elapsed_seconds=row["elapsed_seconds"],
    )
