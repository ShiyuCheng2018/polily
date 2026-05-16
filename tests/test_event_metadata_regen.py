"""v0.12.0: honor Polymarket's `context_requires_regen` flag.

Polymarket's eventMetadata JSON includes:
    context_description: str   # Polymarket's auto-generated event blurb
    context_requires_regen: bool  # set by Polymarket when the description has gone stale
    context_updated_at: str    # Polymarket's last-regenerated timestamp

When the flag is true, Polymarket signals "you should re-fetch — my cached
description is out of date." Pre-v0.12.0, polily fetched once on event
discovery and never re-fetched, so the description went stale silently.
The agent caught this in dev_feedback for event 206793 (Iran uranium):
the stored description missed 5/6-5/7 14-point MOU news despite the flag
being true.

Fix: add a periodic regen step inside the daemon's global poll. Every
tick, query monitored events whose stored event_metadata has the flag
set, refetch from Gamma if not within rate-limit cooldown, and update
the row.

Rate limit: in-memory `{event_id: last_attempt_at}` dict, default 5-minute
cooldown to prevent hammering Polymarket while they regenerate
asynchronously.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from polily.core.db import PolilyDB
from polily.daemon.event_metadata_regen import (
    _last_regen_attempt,
    regen_stale_event_descriptions,
)


def _seed_event(
    db: PolilyDB,
    *,
    event_id: str,
    slug: str,
    metadata: dict | None,
    monitored: bool = True,
) -> None:
    """Insert a minimal monitored event with optional event_metadata JSON."""
    now = datetime.now(UTC).isoformat()
    meta_str = json.dumps(metadata) if metadata else None
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO events(event_id, title, slug, event_metadata, "
            "active, closed, market_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 1, 0, 1, ?, ?)",
            (event_id, f"Test event {event_id}", slug, meta_str, now, now),
        )
        if monitored:
            conn.execute(
                "INSERT INTO event_monitors(event_id, auto_monitor, updated_at) "
                "VALUES (?, 1, ?)",
                (event_id, now),
            )


@pytest.fixture(autouse=True)
def _reset_cooldown_cache():
    _last_regen_attempt.clear()
    yield
    _last_regen_attempt.clear()


@pytest.mark.asyncio
async def test_regen_fires_when_flag_true_and_updates_metadata(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD blurb",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    _seed_event(db, event_id="ev1", slug="iran-uranium-q2-2026", metadata=stale)

    fresh_response = {
        "id": "ev1",
        "slug": "iran-uranium-q2-2026",
        "eventMetadata": {
            "context_description": "FRESH blurb with 5/7 MOU news",
            "context_requires_regen": False,
            "context_updated_at": "2026-05-10T00:00:00.000Z",
        },
    }

    fake_fetch = AsyncMock(return_value=fresh_response)
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 1, "Expected exactly one event to be regenerated"
    fake_fetch.assert_awaited_once()

    row = db.conn.execute(
        "SELECT event_metadata FROM events WHERE event_id='ev1'",
    ).fetchone()
    parsed = json.loads(row["event_metadata"])
    assert parsed["context_description"] == "FRESH blurb with 5/7 MOU news"
    assert parsed["context_requires_regen"] is False


@pytest.mark.asyncio
async def test_regen_skips_when_flag_false(tmp_path):
    db = PolilyDB(tmp_path / "polily.db")
    fresh = {
        "context_description": "Already fresh",
        "context_requires_regen": False,
        "context_updated_at": "2026-05-10T00:00:00.000Z",
    }
    _seed_event(db, event_id="ev1", slug="some-slug", metadata=fresh)

    fake_fetch = AsyncMock()
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0
    fake_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_regen_skips_when_metadata_missing(tmp_path):
    """Events with no event_metadata column value (NULL) → no flag → skip."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event(db, event_id="ev1", slug="some-slug", metadata=None)

    fake_fetch = AsyncMock()
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0
    fake_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_regen_skips_unmonitored_events(tmp_path):
    """Only events with auto_monitor=1 are eligible — un-monitored events
    don't drive analyses, so refetching their metadata wastes API quota."""
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    _seed_event(
        db, event_id="ev1", slug="some-slug", metadata=stale, monitored=False,
    )

    fake_fetch = AsyncMock()
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0
    fake_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_regen_respects_cooldown_within_window(tmp_path):
    """Within the cooldown window (default 5 min), a second call must not
    refetch — even if the flag is still true. Prevents API hammering when
    Polymarket takes time to regenerate."""
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    _seed_event(db, event_id="ev1", slug="some-slug", metadata=stale)

    response = {
        "id": "ev1",
        "slug": "some-slug",
        "eventMetadata": {**stale, "context_requires_regen": True},
    }
    fake_fetch = AsyncMock(return_value=response)
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        # First call — fires
        n1 = await regen_stale_event_descriptions(db, config=None)
        # Second call immediately after — should be cooldown-skipped
        n2 = await regen_stale_event_descriptions(db, config=None)

    assert n1 == 1
    assert n2 == 0, "Cooldown must prevent immediate re-attempt"
    assert fake_fetch.await_count == 1


@pytest.mark.asyncio
async def test_regen_handles_fetch_failure_without_blanking_row(tmp_path):
    """If Gamma returns None (404 / network error), keep the existing
    event_metadata in DB. We never want to overwrite real data with
    nothing on a transient failure."""
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD but valuable",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    _seed_event(db, event_id="ev1", slug="some-slug", metadata=stale)

    fake_fetch = AsyncMock(return_value=None)
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0
    fake_fetch.assert_awaited_once()

    row = db.conn.execute(
        "SELECT event_metadata FROM events WHERE event_id='ev1'",
    ).fetchone()
    parsed = json.loads(row["event_metadata"])
    assert parsed["context_description"] == "OLD but valuable", (
        "Failed fetch must not blank existing metadata"
    )


@pytest.mark.asyncio
async def test_regen_handles_non_dict_metadata_response(tmp_path):
    """v0.12.0 code-review hardening: if Polymarket returns a malformed
    eventMetadata (string scalar, list, anything non-dict), the regen
    must NOT overwrite the existing row. json.dumps() would happily
    serialize a string into the JSON column, but downstream callers
    expect a dict — silent garbage write would crash event_metadata
    consumers (TUI rendering, agent context-description access).
    """
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD but valid",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    _seed_event(db, event_id="ev1", slug="some-slug", metadata=stale)

    # Polymarket returns eventMetadata as a string (malformed)
    response = {"id": "ev1", "slug": "some-slug", "eventMetadata": "garbage string"}
    fake_fetch = AsyncMock(return_value=response)
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0

    row = db.conn.execute(
        "SELECT event_metadata FROM events WHERE event_id='ev1'",
    ).fetchone()
    parsed = json.loads(row["event_metadata"])
    assert isinstance(parsed, dict), (
        "Existing event_metadata must remain a dict — never overwrite with non-dict garbage"
    )
    assert parsed["context_description"] == "OLD but valid"


@pytest.mark.asyncio
async def test_regen_handles_response_without_metadata(tmp_path):
    """Some events have no eventMetadata at all in the Gamma response.
    Don't error — leave existing data alone."""
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    _seed_event(db, event_id="ev1", slug="some-slug", metadata=stale)

    response = {"id": "ev1", "slug": "some-slug"}  # no eventMetadata key
    fake_fetch = AsyncMock(return_value=response)
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0

    row = db.conn.execute(
        "SELECT event_metadata FROM events WHERE event_id='ev1'",
    ).fetchone()
    parsed = json.loads(row["event_metadata"])
    assert parsed["context_description"] == "OLD"


@pytest.mark.asyncio
async def test_regen_skips_when_event_lacks_slug(tmp_path):
    """Slug is required to call fetch_event_by_slug. Defensive: never throw
    on a row missing a slug (legacy data could exist)."""
    db = PolilyDB(tmp_path / "polily.db")
    stale = {
        "context_description": "OLD",
        "context_requires_regen": True,
        "context_updated_at": "2026-05-06T00:00:00.000Z",
    }
    # Insert with NULL slug
    now = datetime.now(UTC).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO events(event_id, title, slug, event_metadata, "
            "active, closed, market_count, created_at, updated_at) "
            "VALUES ('ev1', 'no slug', NULL, ?, 1, 0, 1, ?, ?)",
            (json.dumps(stale), now, now),
        )
        conn.execute(
            "INSERT INTO event_monitors(event_id, auto_monitor, updated_at) "
            "VALUES ('ev1', 1, ?)",
            (now,),
        )

    fake_fetch = AsyncMock()
    with patch(
        "polily.api.PolymarketClient.fetch_event_by_slug", fake_fetch,
    ):
        n = await regen_stale_event_descriptions(db, config=None)
    assert n == 0
    fake_fetch.assert_not_awaited()
