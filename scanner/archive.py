"""Scan archive: save, load, and query archived scan results."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from scanner.reporting import TierResult, render_candidate_json

logger = logging.getLogger(__name__)


def save_scan_unified(tiers: TierResult, archive_dir: str, scan_id: str | None = None) -> str:
    """Save all tiers to a single archive with tier labels. Returns scan_id (timestamp)."""
    Path(archive_dir).mkdir(parents=True, exist_ok=True)

    output = []
    for tier_name, candidates in [("research", tiers.tier_a), ("watchlist", tiers.tier_b), ("filtered", tiers.tier_c)]:
        for c in candidates:
            entry = json.loads(render_candidate_json(c))
            entry["tier"] = tier_name
            output.append(entry)

    if not scan_id:
        scan_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    archive_path = Path(archive_dir) / f"{scan_id}.json"
    with open(archive_path, "w") as f:
        json.dump(output, f, indent=2, default=str)
    return scan_id




def load_latest_archive(archive_dir: str | Path) -> list[dict] | None:
    """Load the most recent scan archive."""
    d = Path(archive_dir)
    if not d.exists():
        return None
    files = list(d.glob("*.json"))
    if not files:
        return None
    latest = max(files)  # filenames are timestamps, so max = latest
    try:
        with open(latest) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load archive %s: %s", latest, e)
        return None


def find_entry_in_archive(market_id: str, archive_dir: str | Path) -> dict | None:
    """Find a market entry in the latest archive by market_id."""
    data = load_latest_archive(archive_dir)
    if not data:
        return None
    for entry in data:
        if entry.get("market_id") == market_id:
            return entry
    return None


def find_entry_by_rank(rank: int, archive_dir: str | Path) -> dict | None:
    """Find a candidate from the latest archive by score rank (1-indexed)."""
    data = load_latest_archive(archive_dir)
    if not data:
        return None
    scored = sorted(data, key=lambda x: x.get("structure_score", 0), reverse=True)
    idx = rank - 1
    if 0 <= idx < len(scored):
        return scored[idx]
    return None


def get_latest_scan_id(archive_dir: str | Path) -> str | None:
    """Get the scan_id (timestamp) of the most recent archive file."""
    d = Path(archive_dir)
    if not d.exists():
        return None
    files = list(d.glob("*.json"))
    if not files:
        return None
    return max(files).stem  # filename without .json = timestamp


def load_demo_data(demo_path: str = "data/fixtures/demo_markets.json") -> list:
    """Load demo fixture data for --demo mode."""
    from scanner.models import Market

    p = Path(demo_path)
    if not p.exists():
        return []
    with open(p) as f:
        data = json.load(f)
    return [Market.model_validate(m) for m in data]
