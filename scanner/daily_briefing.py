"""Daily briefing: compare today vs yesterday scans, track deltas."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class MarketDelta:
    market_id: str
    title: str
    yesterday_price: float | None
    today_price: float | None
    price_change_pct: float | None
    yesterday_score: float | None
    today_score: float | None
    yesterday_mispricing: str | None
    today_mispricing: str | None
    disappeared: bool = False


@dataclass
class DailyBriefing:
    deltas: list[MarketDelta]
    new_markets: list[dict]
    summary: str


def load_latest_archives(
    archive_dir: Path,
) -> tuple[list[dict] | None, list[dict] | None]:
    """Load the two most recent scan archives.

    Returns (today_data, yesterday_data). Either can be None.
    """
    if not archive_dir.exists():
        return None, None

    archives = sorted(archive_dir.glob("*.json"))
    if not archives:
        return None, None

    today = _load_json(archives[-1])
    yesterday = _load_json(archives[-2]) if len(archives) >= 2 else None
    return today, yesterday


def compute_deltas(
    today: list[dict],
    yesterday: list[dict],
) -> list[MarketDelta]:
    """Compute price and score deltas for markets present in both scans."""
    if not today and not yesterday:
        return []

    today_by_id = {m["market_id"]: m for m in today}
    yesterday_by_id = {m["market_id"]: m for m in yesterday}

    deltas = []

    # Markets in yesterday: check if still present today
    for mid, ym in yesterday_by_id.items():
        tm = today_by_id.get(mid)
        if tm:
            yp = ym.get("yes_price")
            tp = tm.get("yes_price")
            change_pct = (tp - yp) / yp if yp and tp and yp != 0 else None
            deltas.append(MarketDelta(
                market_id=mid,
                title=ym.get("title", ""),
                yesterday_price=yp,
                today_price=tp,
                price_change_pct=change_pct,
                yesterday_score=ym.get("structure_score"),
                today_score=tm.get("structure_score"),
                yesterday_mispricing=ym.get("mispricing_signal"),
                today_mispricing=tm.get("mispricing_signal"),
            ))
        else:
            # Market disappeared (resolved or removed)
            deltas.append(MarketDelta(
                market_id=mid,
                title=ym.get("title", ""),
                yesterday_price=ym.get("yes_price"),
                today_price=None,
                price_change_pct=None,
                yesterday_score=ym.get("structure_score"),
                today_score=None,
                yesterday_mispricing=ym.get("mispricing_signal"),
                today_mispricing=None,
                disappeared=True,
            ))

    return deltas


def generate_briefing(archive_dir: Path) -> DailyBriefing:
    """Generate a daily briefing from scan archives."""
    today_data, yesterday_data = load_latest_archives(archive_dir)

    if today_data is None:
        return DailyBriefing(deltas=[], new_markets=[], summary="No scan archives found.")

    if yesterday_data is None:
        return DailyBriefing(
            deltas=[],
            new_markets=today_data,
            summary=f"First scan — {len(today_data)} candidates found. No prior data to compare.",
        )

    deltas = compute_deltas(today_data, yesterday_data)

    # New markets = in today but not in yesterday
    yesterday_ids = {m["market_id"] for m in yesterday_data}
    new_markets = [m for m in today_data if m["market_id"] not in yesterday_ids]

    # Summary
    movers = [d for d in deltas if d.price_change_pct and abs(d.price_change_pct) > 0.05]
    disappeared = [d for d in deltas if d.disappeared]

    parts = [f"{len(deltas)} tracked markets"]
    if movers:
        parts.append(f"{len(movers)} moved >5%")
    if disappeared:
        parts.append(f"{len(disappeared)} resolved/removed")
    if new_markets:
        parts.append(f"{len(new_markets)} new")

    summary = "Yesterday → Today: " + ", ".join(parts) + "."

    return DailyBriefing(deltas=deltas, new_markets=new_markets, summary=summary)


def _load_json(path: Path) -> list[dict] | None:
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load archive %s: %s", path, e)
        return None
