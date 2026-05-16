"""Honor Polymarket's `context_requires_regen` flag (v0.12.0).

Background — what the flag is:
    Polymarket's Gamma API returns an `eventMetadata` JSON object on
    every event. Three fields matter for monitoring:

        context_description    str   # Polymarket-curated event blurb
        context_requires_regen bool  # set by Polymarket when stale
        context_updated_at     str   # Polymarket's last-regenerated time

    `context_requires_regen=true` is Polymarket's way of saying: "this
    description is out of date, you should re-call my API to get a
    fresh one." Polymarket regenerates asynchronously on their side;
    the flag flips back to false once they finish.

What polily did before this module:
    Fetched the event once on first discovery, stored the metadata
    snapshot in `events.event_metadata` (JSON column), never re-checked
    the flag. Result: long-monitored events accumulated stale
    descriptions silently — agent dev_feedback caught this on event
    206793 ("Iran agrees to end enrichment of uranium by June 30?")
    where the description missed 5/6-5/7 14-point MOU news despite
    `context_requires_regen=true`.

What this module does:
    Once per global poll tick (called from `poll_job._global_poll`
    Step 2.7), scan monitored events for `context_requires_regen=true`
    in their stored metadata. For each, refetch via
    `PolymarketClient.fetch_event_by_slug` if not within the cooldown
    window, and update the row.

Rate limit:
    In-memory `_last_regen_attempt: {event_id: datetime}` dict with a
    5-minute cooldown. Prevents API hammering when Polymarket leaves
    the flag set while regenerating async. Lost on daemon restart;
    that's acceptable (daemon restarts are rare and the next tick
    re-attempts naturally).

Invariants:
    * Failed fetch (None response, missing eventMetadata) NEVER blanks
      the existing row — defensive against transient errors.
    * Only monitored events (auto_monitor=1) are eligible.
    * Events without a slug are silently skipped (defensive against
      legacy data).
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from polily.core.db import PolilyDB

logger = logging.getLogger(__name__)

# Cooldown window — how long to wait between refetch attempts on the same
# event when Polymarket leaves the flag set. 5 minutes is conservative:
# their typical regen latency is sub-minute, so the second tick after a
# stale-flag observation will pick up the fresh description, but we still
# back off if they're slow.
_REGEN_COOLDOWN_SECONDS = 300

# Module-level rate-limit cache. Survives across calls within a single
# daemon process; cleared on daemon restart.
_last_regen_attempt: dict[str, datetime] = {}


async def regen_stale_event_descriptions(db: PolilyDB, config) -> int:
    """Refetch event_metadata for monitored events whose stored snapshot
    has `context_requires_regen=true` and was last attempted outside
    the cooldown window.

    Args:
        db: live PolilyDB handle
        config: PolilyConfig (used to construct PolymarketClient with
            the project's api config). Pass None to use Pydantic
            defaults — fine for tests.

    Returns:
        Count of events whose row was actually updated. Skipped events
        (cooldown / fetch failure / no metadata in response) don't count.
    """
    from polily.api import PolymarketClient
    from polily.core.config import PolilyConfig

    # Step 1: pull candidates from DB. Filter on auto_monitor=1 and
    # presence of metadata flag at the SQL boundary so we don't allocate
    # rows we're going to throw away.
    with db.transaction() as conn:
        rows = conn.execute(
            """
            SELECT e.event_id, e.slug, e.event_metadata
            FROM events e
            JOIN event_monitors em ON e.event_id = em.event_id
            WHERE em.auto_monitor = 1
              AND e.closed = 0
              AND e.event_metadata IS NOT NULL
              AND e.event_metadata LIKE '%"context_requires_regen": true%'
            """,
        ).fetchall()

    if not rows:
        return 0

    # Step 2: filter by cooldown + slug presence in Python (cheap)
    candidates: list[tuple[str, str]] = []  # (event_id, slug)
    now = datetime.now(UTC)
    for r in rows:
        eid = r["event_id"]
        slug = r["slug"]
        if not slug:
            logger.debug("Skipping regen for %s — no slug", eid)
            continue
        last = _last_regen_attempt.get(eid)
        if last is not None:
            elapsed = (now - last).total_seconds()
            if elapsed < _REGEN_COOLDOWN_SECONDS:
                continue
        # Re-parse to confirm flag is actually true (the LIKE filter is
        # a substring check; a description containing the literal text
        # could false-match. The defensive parse is cheap.)
        try:
            meta = json.loads(r["event_metadata"])
        except (TypeError, json.JSONDecodeError):
            logger.debug("Skipping regen for %s — malformed metadata JSON", eid)
            continue
        if meta.get("context_requires_regen") is not True:
            continue
        candidates.append((eid, slug))

    if not candidates:
        return 0

    # Step 3: refetch + update. One client per pass; close at the end.
    client_config = config.api if config else PolilyConfig().api
    client = PolymarketClient(client_config)
    updated = 0
    try:
        for event_id, slug in candidates:
            # Stamp the attempt BEFORE the network call so a crash mid-fetch
            # doesn't immediately retry on the next tick.
            _last_regen_attempt[event_id] = datetime.now(UTC)

            try:
                fresh = await client.fetch_event_by_slug(slug)
            except Exception:
                logger.exception(
                    "Regen fetch raised for event %s (slug=%s); leaving row alone",
                    event_id, slug,
                )
                continue

            if not fresh:
                logger.debug(
                    "Regen fetch returned None for event %s (slug=%s); "
                    "Polymarket may have removed the slug. Leaving row alone.",
                    event_id, slug,
                )
                continue

            new_meta = fresh.get("eventMetadata")
            if not new_meta:
                logger.debug(
                    "Regen response for %s lacks eventMetadata; "
                    "leaving row alone.", event_id,
                )
                continue
            # Defensive: Polymarket has occasionally returned eventMetadata
            # as a string scalar or list (malformed payload). json.dumps()
            # would serialize either to a valid JSON string, but the
            # events.event_metadata column is contractually a dict (TUI
            # rendering + agent context_description access). Reject
            # non-dict shapes to preserve the contract — leave the
            # existing row untouched so the next tick can retry.
            if not isinstance(new_meta, dict):
                logger.warning(
                    "Regen response for %s returned non-dict eventMetadata "
                    "(type=%s); leaving row alone.",
                    event_id, type(new_meta).__name__,
                )
                continue

            # Update in-place. Use a transaction so the write is atomic
            # against concurrent reads.
            with db.transaction() as conn:
                conn.execute(
                    "UPDATE events SET event_metadata = ?, updated_at = ? "
                    "WHERE event_id = ?",
                    (json.dumps(new_meta), datetime.now(UTC).isoformat(),
                     event_id),
                )
            updated += 1
            new_flag = new_meta.get("context_requires_regen")
            logger.info(
                "Regenerated event_metadata for %s (slug=%s); "
                "context_requires_regen now %s",
                event_id, slug, new_flag,
            )
    finally:
        await client.close()

    return updated
