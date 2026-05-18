"""Verify v0.12.x ephemeral block injects `event_metadata_freshness:` for
events with usable `context_updated_at` (T-2).

Background: Polymarket's `eventMetadata.context_requires_regen` flag is
empirically unreliable — agent dev_feedback on 3 of 4 monitored events
(108031 / 73106 / 51456, 2026-05-15) caught stale descriptions while
the flag stayed false. polily's existing regen mechanism honors the
flag, so it never fired for those events; the agent had to detect
staleness itself by parsing `context_updated_at`.

T-2 (reframed from "time-based hard regen", which didn't make sense
since Polymarket owns the data) injects a polily-computed staleness
label + WebSearch guidance directly into the prompt. Agent no longer
has to parse the timestamp + compute the age + decide on staleness;
polily labels it ("fresh"/"stale"/"very_stale") and tells the agent
what to do.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB


def _make_agent() -> NarrativeWriterAgent:
    return NarrativeWriterAgent(AgentConfig())


def _build_prompt(db: PolilyDB, event_id: str, *, trigger_source: str = "manual") -> str:
    return _make_agent()._build_prompt(
        event_id=event_id,
        has_position=False,
        position_summary=None,
        db=db,
        trigger_source=trigger_source,
    )


def _ephemeral_section(prompt: str) -> str:
    """Return only the per-call ephemeral block (everything before the first
    `---` separator). Used so assertions don't false-match against the
    manual.md documentation of these same fields.
    """
    head, *_rest = prompt.split("\n\n---\n\n", maxsplit=1)
    return head


def _seed_event(
    db: PolilyDB,
    *,
    event_id: str,
    context_updated_at: str | None,
    context_requires_regen: bool = False,
    description: str = "test event",
    invalid_metadata: bool = False,
) -> None:
    """Seed an event row with a custom event_metadata JSON.

    `invalid_metadata=True` writes literal garbage to the column to test
    graceful-degradation on malformed JSON.
    """
    now = datetime.now(UTC).isoformat()
    if invalid_metadata:
        meta_str = "{not valid json"
    elif context_updated_at is None:
        meta_str = json.dumps({
            "context_description": description,
            "context_requires_regen": context_requires_regen,
        })
    else:
        meta_str = json.dumps({
            "context_description": description,
            "context_updated_at": context_updated_at,
            "context_requires_regen": context_requires_regen,
        })

    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO events (event_id, title, event_metadata, "
            "market_count, updated_at) VALUES (?, ?, ?, 1, ?)",
            (event_id, f"Test event {event_id}", meta_str, now),
        )


def _seed_event_no_metadata(db: PolilyDB, *, event_id: str) -> None:
    """Seed an event row with event_metadata NULL — represents events
    fetched from older API responses or before metadata existed."""
    now = datetime.now(UTC).isoformat()
    with db.transaction() as conn:
        conn.execute(
            "INSERT INTO events (event_id, title, event_metadata, "
            "market_count, updated_at) VALUES (?, ?, NULL, 1, ?)",
            (event_id, f"Test event {event_id}", now),
        )


# ---------------------------------------------------------------------------
# Acceptance #1-3 — staleness label tiers
# ---------------------------------------------------------------------------


def test_fresh_metadata_labels_staleness_fresh(tmp_path):
    """Metadata <24h old → `staleness: "fresh"` and guidance permits
    using as baseline (no MUST WebSearch).
    """
    db = PolilyDB(tmp_path / "polily.db")
    fresh_ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    _seed_event(db, event_id="evt_fresh", context_updated_at=fresh_ts)

    block = _ephemeral_section(_build_prompt(db, "evt_fresh"))

    assert "event_metadata_freshness:" in block, (
        "ephemeral block missing event_metadata_freshness: subsection"
    )
    assert "staleness: 'fresh'" in block, f"got: {block!r}"
    # guidance for fresh shouldn't contain MUST / DO NOT — it's permissive
    assert "MUST" not in block.split("event_metadata_freshness:")[1].split("\n\n")[0], (
        "fresh-tier guidance must not include imperative WebSearch language"
    )


def test_stale_metadata_24_to_72h_labels_staleness_stale(tmp_path):
    """Metadata 24-72h old → `staleness: "stale"` and guidance
    *recommends* (not mandates) WebSearch supplementation.
    """
    db = PolilyDB(tmp_path / "polily.db")
    stale_ts = (datetime.now(UTC) - timedelta(hours=36)).isoformat()
    _seed_event(db, event_id="evt_stale", context_updated_at=stale_ts)

    block = _ephemeral_section(_build_prompt(db, "evt_stale"))

    assert "staleness: 'stale'" in block, f"got: {block!r}"
    # Should include "WebSearch" reference but not the strict imperative
    freshness_section = block.split("event_metadata_freshness:")[1]
    assert "WebSearch" in freshness_section or "websearch" in freshness_section.lower(), (
        "stale-tier guidance should mention WebSearch supplementation"
    )


def test_very_stale_metadata_over_72h_labels_staleness_very_stale(tmp_path):
    """Metadata >72h old → `staleness: "very_stale"` and guidance
    MANDATES WebSearch ("MUST" or "DO NOT use as authoritative" etc).

    This is the case that matters most — matches the user's 5/15
    feedback on event 108031 where context was 5 days stale.
    """
    db = PolilyDB(tmp_path / "polily.db")
    very_stale_ts = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    _seed_event(db, event_id="evt_very_stale",
                context_updated_at=very_stale_ts,
                context_requires_regen=False)

    block = _ephemeral_section(_build_prompt(db, "evt_very_stale"))

    assert "staleness: 'very_stale'" in block, f"got: {block!r}"
    # Very-stale tier MUST include strict guidance
    freshness_section = block.split("event_metadata_freshness:")[1]
    has_strict_guidance = (
        "MUST" in freshness_section
        or "DO NOT" in freshness_section
        or "mandatory" in freshness_section.lower()
    )
    assert has_strict_guidance, (
        f"very_stale guidance must include strict language (MUST / "
        f"DO NOT / mandatory) — got: {freshness_section[:300]!r}"
    )


# ---------------------------------------------------------------------------
# Acceptance #4-6 — graceful handling of missing / malformed data
# ---------------------------------------------------------------------------


def test_missing_event_metadata_column_omits_injection(tmp_path):
    """`events.event_metadata IS NULL` → no `event_metadata_freshness:`
    section. Common for older events fetched before metadata flow existed,
    or scan-pipeline failures."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event_no_metadata(db, event_id="evt_null")

    block = _ephemeral_section(_build_prompt(db, "evt_null"))
    assert "event_metadata_freshness:" not in block


def test_malformed_metadata_json_omits_injection(tmp_path):
    """`events.event_metadata` containing invalid JSON → no injection
    (graceful, not crash). polily's regen runs on the daemon side; a
    parse failure here shouldn't take down the analysis."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event(db, event_id="evt_malformed",
                context_updated_at=None, invalid_metadata=True)

    block = _ephemeral_section(_build_prompt(db, "evt_malformed"))
    assert "event_metadata_freshness:" not in block


def test_missing_context_updated_at_omits_injection(tmp_path):
    """Valid JSON but no `context_updated_at` field → no injection.
    Without a timestamp we can't compute age; safer to omit than to
    invent a fake label."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_event(db, event_id="evt_no_ts", context_updated_at=None,
                description="some context")

    block = _ephemeral_section(_build_prompt(db, "evt_no_ts"))
    assert "event_metadata_freshness:" not in block


def test_non_dict_event_metadata_omits_injection(tmp_path):
    """`event_metadata` is JSON-parseable but not a dict (e.g. Polymarket
    one day returns `eventMetadata: []` or `eventMetadata: "string"` or
    `eventMetadata: null` after parsing). The helper must accept the
    parse but reject the type — calling `.get()` on a list or string
    would crash without the `isinstance(meta, dict)` guard."""
    db = PolilyDB(tmp_path / "polily.db")
    now = datetime.now(UTC).isoformat()
    # Seed three problematic shapes directly via SQL — the higher-level
    # _seed_event helper assumes a dict shape we want to bypass.
    with db.transaction() as conn:
        # 1. JSON array
        conn.execute(
            "INSERT INTO events (event_id, title, event_metadata, "
            "market_count, updated_at) VALUES (?, ?, ?, 1, ?)",
            ("evt_meta_list", "list-shape", "[]", now),
        )
        # 2. JSON string scalar
        conn.execute(
            "INSERT INTO events (event_id, title, event_metadata, "
            "market_count, updated_at) VALUES (?, ?, ?, 1, ?)",
            ("evt_meta_str", "scalar-shape", '"just a string"', now),
        )
        # 3. JSON null
        conn.execute(
            "INSERT INTO events (event_id, title, event_metadata, "
            "market_count, updated_at) VALUES (?, ?, ?, 1, ?)",
            ("evt_meta_null", "json-null", "null", now),
        )

    for event_id in ("evt_meta_list", "evt_meta_str", "evt_meta_null"):
        block = _ephemeral_section(_build_prompt(db, event_id))
        assert "event_metadata_freshness:" not in block, (
            f"Non-dict event_metadata ({event_id!r}) must NOT crash and "
            f"must NOT emit a freshness block — got block: {block!r}"
        )


# ---------------------------------------------------------------------------
# Acceptance #7 — Polymarket flag value is faithfully exposed
# ---------------------------------------------------------------------------


def test_polymarket_flag_set_reflects_context_requires_regen(tmp_path):
    """When Polymarket has `context_requires_regen: true`, the injected
    block must say `polymarket_flag_set: true`. Agent uses this to
    distinguish "we're refetching" from "Polymarket says it's fine but
    polily thinks it's stale anyway"."""
    db = PolilyDB(tmp_path / "polily.db")
    stale_ts = (datetime.now(UTC) - timedelta(hours=48)).isoformat()
    _seed_event(db, event_id="evt_flag_on",
                context_updated_at=stale_ts,
                context_requires_regen=True)
    _seed_event(db, event_id="evt_flag_off",
                context_updated_at=stale_ts,
                context_requires_regen=False)

    block_on = _ephemeral_section(_build_prompt(db, "evt_flag_on"))
    block_off = _ephemeral_section(_build_prompt(db, "evt_flag_off"))

    assert "polymarket_flag_set: true" in block_on
    assert "polymarket_flag_set: false" in block_off


# ---------------------------------------------------------------------------
# Acceptance #8 — injection applies to all trigger types
# ---------------------------------------------------------------------------


def test_injection_applies_to_all_trigger_sources(tmp_path):
    """Metadata staleness matters for every analysis path — manual,
    scan, scheduled, AND movement. Unlike `triggering_movements:`
    (which is movement-specific), this freshness check is unconditional
    (when metadata exists)."""
    db = PolilyDB(tmp_path / "polily.db")
    fresh_ts = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    _seed_event(db, event_id="evt_all", context_updated_at=fresh_ts)

    for trigger in ("manual", "scan", "scheduled", "movement"):
        block = _ephemeral_section(_build_prompt(db, "evt_all",
                                                  trigger_source=trigger))
        assert "event_metadata_freshness:" in block, (
            f"trigger_source={trigger!r}: ephemeral block missing freshness "
            f"section (must inject regardless of trigger type)"
        )


# ---------------------------------------------------------------------------
# Regression — existing ephemeral structure preserved
# ---------------------------------------------------------------------------


def test_baseline_ephemeral_fields_still_present_with_freshness_injection(tmp_path):
    """The new freshness section is additive: existing per-call inputs
    (event_id, trigger, has_position, official_strategy_path) must
    still appear unchanged. Guards against an accidental reorder /
    omission while wiring up the new block."""
    db = PolilyDB(tmp_path / "polily.db")
    fresh_ts = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    _seed_event(db, event_id="evt_regress", context_updated_at=fresh_ts)

    prompt = _build_prompt(db, "evt_regress", trigger_source="manual")
    assert "event_id: evt_regress" in prompt
    assert "trigger: manual" in prompt
    assert "has_position: false" in prompt
    assert "official_strategy_path:" in prompt
    # And the new section
    assert "event_metadata_freshness:" in prompt
