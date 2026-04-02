"""Analysis store: persist per-market AI analysis versions in SQLite."""

import json
import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class AnalysisVersion(BaseModel):
    """A single AI analysis snapshot for a market."""

    version: int  # 1-indexed
    created_at: str  # ISO 8601
    market_title: str
    yes_price_at_analysis: float | None = None

    # Trigger metadata
    trigger_source: str = "manual"  # manual / scan / scheduled
    watch_sequence: int = 0
    price_at_watch: float | None = None

    # Agent outputs (stored as JSON TEXT in SQLite)
    analyst_output: dict = {}
    narrative_output: dict = {}

    # Score snapshot
    structure_score: float | None = None
    score_breakdown: dict | None = None

    # Mispricing
    mispricing_signal: str = "none"
    mispricing_details: str | None = None

    # Metadata
    elapsed_seconds: float = 0.0


def append_analysis(market_id: str, version: AnalysisVersion, db) -> None:
    """Append an analysis version. No version limit."""
    db.conn.execute(
        """INSERT INTO analyses
        (market_id, version, created_at, market_title, yes_price_at_analysis,
         trigger_source, watch_sequence, price_at_watch,
         analyst_output, narrative_output,
         structure_score, score_breakdown,
         mispricing_signal, mispricing_details, elapsed_seconds)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            market_id, version.version, version.created_at, version.market_title,
            version.yes_price_at_analysis,
            version.trigger_source, version.watch_sequence, version.price_at_watch,
            json.dumps(version.analyst_output, ensure_ascii=False),
            json.dumps(version.narrative_output, ensure_ascii=False),
            version.structure_score,
            json.dumps(version.score_breakdown, ensure_ascii=False) if version.score_breakdown else None,
            version.mispricing_signal, version.mispricing_details,
            version.elapsed_seconds,
        ),
    )
    db.conn.commit()


def get_market_analyses(market_id: str, db) -> list[AnalysisVersion]:
    """Get all analysis versions for a market, ordered by version."""
    rows = db.conn.execute(
        "SELECT * FROM analyses WHERE market_id = ? ORDER BY version ASC",
        (market_id,),
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
        market_title=row["market_title"],
        yes_price_at_analysis=row["yes_price_at_analysis"],
        trigger_source=row["trigger_source"],
        watch_sequence=row["watch_sequence"],
        price_at_watch=row["price_at_watch"],
        analyst_output=json.loads(row["analyst_output"]) if row["analyst_output"] else {},
        narrative_output=json.loads(row["narrative_output"]) if row["narrative_output"] else {},
        structure_score=row["structure_score"],
        score_breakdown=json.loads(row["score_breakdown"]) if row["score_breakdown"] else None,
        mispricing_signal=row["mispricing_signal"],
        mispricing_details=row["mispricing_details"],
        elapsed_seconds=row["elapsed_seconds"],
    )
