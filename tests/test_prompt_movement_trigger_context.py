"""Verify v0.12.x ephemeral block injects `triggering_movements` when
`trigger_source == "movement"` (T-1).

Without this, the agent sees only `trigger: movement` (one string) and has
to reverse-engineer the cross-market context via Read tool against
`movement_log`. That's fragile (manual.md teaches the schema but doesn't
mandate the query — agent may skip), token-costly (each agent SELECT is a
tool invocation), and timing-misaligned (agent's query happens 5-15s
after polily's decision).

Method A: `_build_prompt` reverse-queries `movement_log` for the event in
the last 60s when `trigger_source == "movement"` and injects each row as
a bullet under a `triggering_movements:` ephemeral subsection, ordered
by magnitude DESC (spike row first).
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from polily.agents.narrative_writer import NarrativeWriterAgent
from polily.core.config import AgentConfig
from polily.core.db import PolilyDB
from polily.monitor.store import append_movement


def _make_agent() -> NarrativeWriterAgent:
    """Build a NarrativeWriterAgent with defaults; tests don't invoke claude CLI."""
    return NarrativeWriterAgent(AgentConfig())


def _build_prompt(db: PolilyDB, event_id: str, *, trigger_source: str) -> str:
    return _make_agent()._build_prompt(
        event_id=event_id,
        has_position=False,
        position_summary=None,
        db=db,
        trigger_source=trigger_source,
    )


def _ephemeral_section(prompt: str) -> str:
    """Return only the ephemeral block (everything before the first `---`
    separator). Used by negative tests to verify that the cross-market
    section isn't being injected into the per-call inputs, distinct
    from manual.md's documentation of the feature which legitimately
    contains the string `triggering_movements:` as an example.
    """
    head, *_rest = prompt.split("\n\n---\n\n", maxsplit=1)
    return head


def _seed_movement(
    db: PolilyDB,
    *,
    event_id: str,
    market_id: str,
    yes_price: float,
    prev_yes_price: float,
    magnitude: float,
    quality: float,
    label: str = "whale_move",
) -> None:
    """Convenience seed for a single movement_log row."""
    append_movement(
        event_id=event_id,
        market_id=market_id,
        yes_price=yes_price,
        prev_yes_price=prev_yes_price,
        magnitude=magnitude,
        quality=quality,
        label=label,
        db=db,
    )


# ---------------------------------------------------------------------------
# Acceptance #1 — movement trigger with seeded siblings → triggering_movements block
# ---------------------------------------------------------------------------


def test_movement_trigger_injects_triggering_movements_block(tmp_path):
    """Seeded movement_log with 3 whale_move siblings + 1 noise sibling →
    the ephemeral block contains a `triggering_movements:` subsection
    with all 4 rows, ordered by magnitude DESC (spike row first).
    """
    db = PolilyDB(tmp_path / "polily.db")
    # 51456 Fed cuts event with 4 sub-markets — the canonical test case
    _seed_movement(db, event_id="51456", market_id="51456-cuts-25bps",
                   yes_price=0.40, prev_yes_price=0.60, magnitude=78, quality=65)
    _seed_movement(db, event_id="51456", market_id="51456-cuts-50bps",
                   yes_price=0.05, prev_yes_price=0.20, magnitude=71, quality=58)
    _seed_movement(db, event_id="51456", market_id="51456-holds",
                   yes_price=0.50, prev_yes_price=0.15, magnitude=82, quality=70)
    _seed_movement(db, event_id="51456", market_id="51456-hikes",
                   yes_price=0.05, prev_yes_price=0.05, magnitude=12, quality=8,
                   label="noise")

    prompt = _build_prompt(db, "51456", trigger_source="movement")

    assert "triggering_movements:" in prompt, (
        "movement-triggered prompt must include a triggering_movements: "
        "subsection — got prompt without it"
    )

    # All 4 market_ids should appear in the section
    for mid in ("51456-cuts-25bps", "51456-cuts-50bps",
                "51456-holds", "51456-hikes"):
        assert mid in prompt, f"market_id {mid!r} missing from prompt"

    # Order: holds (M=82) > cuts-25bps (78) > cuts-50bps (71) > hikes (12)
    # We assert by character position of each market_id in the prompt.
    section_start = prompt.find("triggering_movements:")
    holds_pos = prompt.find("51456-holds", section_start)
    cuts25_pos = prompt.find("51456-cuts-25bps", section_start)
    cuts50_pos = prompt.find("51456-cuts-50bps", section_start)
    hikes_pos = prompt.find("51456-hikes", section_start)
    assert holds_pos < cuts25_pos < cuts50_pos < hikes_pos, (
        f"triggering_movements not sorted by magnitude DESC; positions: "
        f"holds={holds_pos} cuts25={cuts25_pos} cuts50={cuts50_pos} "
        f"hikes={hikes_pos} (expected holds first since M=82 is the max)"
    )


# ---------------------------------------------------------------------------
# Acceptance #2 — movement trigger with empty movement_log → no stub header
# ---------------------------------------------------------------------------


def test_movement_trigger_with_empty_movement_log_omits_section(tmp_path):
    """If movement_log is empty (e.g., transient state, race, or testing),
    don't emit a `triggering_movements:` header with nothing under it —
    a bare header would confuse the agent ('what is this section about').
    """
    db = PolilyDB(tmp_path / "polily.db")
    # No movements seeded

    prompt = _build_prompt(db, "evt_empty", trigger_source="movement")

    # Trigger string still present (we're not removing baseline ephemeral)
    assert "trigger: movement" in prompt
    # ...but the cross-market section must NOT appear with no data.
    # Check only the ephemeral block — manual.md legitimately contains
    # `triggering_movements:` as documentation of the feature.
    assert "triggering_movements:" not in _ephemeral_section(prompt), (
        "Empty movement_log must NOT produce a bare triggering_movements: "
        "header — graceful absence is better than empty section"
    )


# ---------------------------------------------------------------------------
# Acceptance #3 — non-movement triggers (manual / scan / scheduled) skip injection
# ---------------------------------------------------------------------------


def test_manual_trigger_does_not_inject_triggering_movements(tmp_path):
    """A manual user-initiated analysis should NOT pull movement context
    even if movement_log happens to have recent rows — the manual trigger
    semantic is 'user wants analysis now', not 'react to detected movement'.
    """
    db = PolilyDB(tmp_path / "polily.db")
    _seed_movement(db, event_id="evt_manual", market_id="evt_manual-A",
                   yes_price=0.50, prev_yes_price=0.30, magnitude=88, quality=72)

    prompt = _build_prompt(db, "evt_manual", trigger_source="manual")

    assert "trigger: manual" in prompt
    assert "triggering_movements:" not in _ephemeral_section(prompt), (
        "manual trigger must not inject triggering_movements — only the "
        "movement trigger gets cross-market context"
    )


def test_scan_trigger_does_not_inject_triggering_movements(tmp_path):
    """Same negative assertion for trigger_source='scan'."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_movement(db, event_id="evt_scan", market_id="evt_scan-A",
                   yes_price=0.50, prev_yes_price=0.30, magnitude=88, quality=72)

    prompt = _build_prompt(db, "evt_scan", trigger_source="scan")

    assert "trigger: scan" in prompt
    assert "triggering_movements:" not in _ephemeral_section(prompt)


def test_scheduled_trigger_does_not_inject_triggering_movements(tmp_path):
    """Same negative assertion for trigger_source='scheduled'."""
    db = PolilyDB(tmp_path / "polily.db")
    _seed_movement(db, event_id="evt_sched", market_id="evt_sched-A",
                   yes_price=0.50, prev_yes_price=0.30, magnitude=88, quality=72)

    prompt = _build_prompt(db, "evt_sched", trigger_source="scheduled")

    assert "trigger: scheduled" in prompt
    assert "triggering_movements:" not in _ephemeral_section(prompt)


# ---------------------------------------------------------------------------
# Acceptance #4 — movements older than the window are excluded
# ---------------------------------------------------------------------------


def test_movements_older_than_window_are_excluded(tmp_path):
    """Movements outside the 60s window (default) must not be injected —
    a movement from 10 minutes ago belongs to a prior decision context,
    not the current trigger.

    Implementation MUST honor the cutoff regardless of whether the agent
    helper reads from `append_movement`-written `created_at` (which uses
    `datetime.now(UTC)`) or via a configurable window — old rows stay out.
    """
    db = PolilyDB(tmp_path / "polily.db")
    # Recent row — should appear
    _seed_movement(db, event_id="evt_window", market_id="evt_window-recent",
                   yes_price=0.50, prev_yes_price=0.30, magnitude=88, quality=72)
    # Then backdate one row's created_at to 10 minutes ago via direct SQL.
    # append_movement always uses now() so we have to mutate after the fact.
    old_iso = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    _seed_movement(db, event_id="evt_window", market_id="evt_window-old",
                   yes_price=0.40, prev_yes_price=0.20, magnitude=95, quality=80)
    with db.transaction() as conn:
        conn.execute(
            "UPDATE movement_log SET created_at = ? "
            "WHERE event_id = 'evt_window' AND market_id = 'evt_window-old'",
            (old_iso,),
        )

    prompt = _build_prompt(db, "evt_window", trigger_source="movement")

    assert "triggering_movements:" in prompt
    assert "evt_window-recent" in prompt, (
        "Recent movement (within 60s window) must appear in injection"
    )
    assert "evt_window-old" not in prompt, (
        "Movement 10 minutes old must be filtered out by the 60s window — "
        "otherwise the prompt carries stale decision context"
    )


# ---------------------------------------------------------------------------
# Regression — baseline ephemeral fields unchanged for non-movement triggers
# ---------------------------------------------------------------------------


def test_non_movement_ephemeral_structure_unchanged(tmp_path):
    """The existing prompt assembly tests (`test_prompt_assembly.py`) cover
    the 4-part structure. This is a defensive guard: the new injection
    must NOT reorder, remove, or accidentally append to non-movement
    triggers' ephemeral blocks.
    """
    db = PolilyDB(tmp_path / "polily.db")
    prompt = _build_prompt(db, "evt_baseline", trigger_source="manual")
    # The canonical anchors from test_prompt_assembly.py still present
    assert "event_id: evt_baseline" in prompt
    assert "trigger: manual" in prompt
    assert "has_position: false" in prompt
    assert "official_strategy_path:" in prompt
    # No movement section in the per-call inputs block
    assert "triggering_movements:" not in _ephemeral_section(prompt)


# ---------------------------------------------------------------------------
# Edge case: NULL prev_yes_price (defensive — schema allows it)
# ---------------------------------------------------------------------------


def test_movement_with_null_prev_yes_price_renders_question_mark(tmp_path):
    """`movement_log.prev_yes_price` is REAL (nullable). The first
    movement entry on a freshly-monitored market may have no prior
    price to diff against. The `_format_movement_line` helper falls
    back to `?` so a partial snapshot still renders cleanly without
    a `:.2f` format crash on None.
    """
    db = PolilyDB(tmp_path / "polily.db")
    # append_movement allows prev_yes_price=None by signature default
    from polily.monitor.store import append_movement
    append_movement(
        event_id="evt_null_prev",
        market_id="evt_null_prev-A",
        yes_price=0.42,
        prev_yes_price=None,  # first observation — no prior to diff
        magnitude=75,
        quality=60,
        label="whale_move",
        db=db,
    )

    prompt = _build_prompt(db, "evt_null_prev", trigger_source="movement")

    # Block emitted (positive case)
    assert "triggering_movements:" in prompt
    # The market row appears
    assert "evt_null_prev-A" in prompt
    # Falls back to `?` for prev_yes_price, real value for yes_price
    # Format: "yes: ?->0.42"
    assert "yes: ?->0.42" in prompt, (
        f"NULL prev_yes_price should render as `?` not crash; "
        f"prompt sample: {prompt[prompt.find('triggering_movements:'):][:300]!r}"
    )
