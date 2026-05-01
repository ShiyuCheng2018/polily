"""Issue A — scan_logs.scheduled_at must be TZ-canonical (UTC) end-to-end.

The original bug: dispatcher's `fetch_overdue_pending` did
`WHERE scheduled_at <= ?` against an ISO 8601 string with arbitrary tz offset.
SQLite compared as TEXT (lex/byte order) so `+08:00` > `+00:00`, making
overdue Beijing rows look "future" forever.

Coverage matrix (A.6 a-o from the user's plan):

  a) write boundary normalizes Beijing tz → UTC ISO
  b) write boundary normalizes Z suffix → +00:00
  c) write boundary preserves naive datetime as UTC
  d) write boundary handles already-UTC value (idempotent)
  e) _validate_next_check_at returns canonical UTC form
  f) _validate_next_check_at rejects past timestamps
  g) _validate_next_check_at rejects malformed strings
  h) fetch_overdue_pending finds Beijing-overdue row (regression)
  i) fetch_overdue_pending excludes truly-future row (Beijing future)
  j) fetch_overdue_pending excludes stale rows beyond threshold
  k) fetch_overdue_pending picks earliest per event
  l) fetch_overdue_pending skips events with running scan
  m) fetch_overdue_pending honors custom stale_threshold_minutes
  n) one-shot migration converts +08:00 rows to +00:00
  o) one-shot migration is idempotent (no-op on already-UTC DB)

R3 round-2 follow-ups (Whis + code-reviewer findings):

  p) v0.7.0 → UTC migration ordering pinned: pre-v0.7.0 DB with +08:00 in
     event_monitors.next_check_at gets seeded into scan_logs AND normalized
     to +00:00 in the same _init_schema cycle (Whis #2)
  q) MIN() in CTE picks time-earliest, not lex-smallest, when raw INSERTs
     bypass A.4.3 + A.4.5 (Whis #1 — fixed by datetime() wrap on MIN/JOIN)
  r) raw +08:00 INSERT (bypassing write-boundary normalize) still gets
     correctly classified as overdue by SQL datetime() parsing (Whis #3)
  s) _validate_next_check_at handles negative TZ offsets (e.g. -05:00 ET)
     (code-reviewer S1 — diversifies TZ matrix beyond Beijing/Z/naive)
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from polily.core.db import PolilyDB
from polily.core.event_store import EventRow, upsert_event
from polily.scan_log import (
    fetch_overdue_pending,
    insert_pending_scan,
)
from polily.tui.service import _validate_next_check_at


@pytest.fixture
def db(tmp_path):
    d = PolilyDB(tmp_path / "tz.db")
    upsert_event(EventRow(event_id="ev1", title="Test1", updated_at="now"), d)
    upsert_event(EventRow(event_id="ev2", title="Test2", updated_at="now"), d)
    yield d
    d.close()


# ---------- a, b, c, d: insert_pending_scan write-boundary normalization ----------

def test_a_insert_normalizes_beijing_tz_to_utc(db):
    # 2026-05-01T18:00:00+08:00 == 2026-05-01T10:00:00+00:00
    sid = insert_pending_scan(
        event_id="ev1", event_title="t",
        scheduled_at="2026-05-01T18:00:00+08:00",
        trigger_source="scheduled", scheduled_reason=None, db=db,
    )
    row = db.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE scan_id=?", (sid,)
    ).fetchone()
    assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"


def test_b_insert_normalizes_z_suffix_to_plus0000(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="t",
        scheduled_at="2026-05-01T10:00:00Z",
        trigger_source="scheduled", scheduled_reason=None, db=db,
    )
    row = db.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE scan_id=?", (sid,)
    ).fetchone()
    assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"


def test_c_insert_treats_naive_datetime_as_utc(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="t",
        scheduled_at="2026-05-01T10:00:00",  # naive — assume UTC
        trigger_source="scheduled", scheduled_reason=None, db=db,
    )
    row = db.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE scan_id=?", (sid,)
    ).fetchone()
    assert row["scheduled_at"].endswith("+00:00")
    assert row["scheduled_at"].startswith("2026-05-01T10:00:00")


def test_d_insert_idempotent_on_already_utc(db):
    sid = insert_pending_scan(
        event_id="ev1", event_title="t",
        scheduled_at="2026-05-01T10:00:00+00:00",
        trigger_source="scheduled", scheduled_reason=None, db=db,
    )
    row = db.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE scan_id=?", (sid,)
    ).fetchone()
    assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"


# ---------- e, f, g: _validate_next_check_at ----------

def test_e_validate_returns_canonical_utc_for_beijing_input():
    future_beijing = (datetime.now(UTC) + timedelta(hours=2)).astimezone(
        timezone(timedelta(hours=8))
    )
    iso_beijing = future_beijing.isoformat()
    out = _validate_next_check_at(iso_beijing)
    assert out is not None
    assert out.endswith("+00:00")
    parsed = datetime.fromisoformat(out)
    assert parsed.tzinfo is UTC
    # Same moment in time
    assert parsed == future_beijing.astimezone(UTC)


def test_f_validate_rejects_past_timestamp():
    past_utc = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert _validate_next_check_at(past_utc) is None


def test_g_validate_rejects_malformed():
    assert _validate_next_check_at("not-a-date") is None
    assert _validate_next_check_at("") is None
    assert _validate_next_check_at(None) is None


# ---------- h, i, j, k, l, m: fetch_overdue_pending semantics ----------

def _make_pending(db, event_id, scheduled_at, scan_id_suffix=""):
    """Insert pending row with explicit scheduled_at — write-boundary will normalize."""
    return insert_pending_scan(
        event_id=event_id, event_title=event_id,
        scheduled_at=scheduled_at,
        trigger_source="scheduled", scheduled_reason=f"r{scan_id_suffix}",
        db=db,
    )


def test_h_fetch_finds_beijing_overdue_row_regression(db):
    """Regression for the original bug — Beijing row 1h overdue should dispatch."""
    # 1 hour ago in Beijing tz
    overdue_beijing = (datetime.now(UTC) - timedelta(minutes=10)).astimezone(
        timezone(timedelta(hours=8))
    )
    sid = _make_pending(db, "ev1", overdue_beijing.isoformat())
    rows = fetch_overdue_pending(db)
    assert len(rows) == 1
    assert rows[0]["scan_id"] == sid


def test_i_fetch_excludes_future_beijing_row(db):
    future_beijing = (datetime.now(UTC) + timedelta(hours=2)).astimezone(
        timezone(timedelta(hours=8))
    )
    _make_pending(db, "ev1", future_beijing.isoformat())
    assert fetch_overdue_pending(db) == []


def test_j_fetch_excludes_stale_rows_beyond_threshold(db):
    # Default threshold = 30 min. 2h-overdue should NOT auto-dispatch.
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    _make_pending(db, "ev1", stale)
    assert fetch_overdue_pending(db) == []


def test_k_fetch_picks_earliest_per_event(db):
    earlier = (datetime.now(UTC) - timedelta(minutes=20)).isoformat()
    later = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    sid_early = _make_pending(db, "ev1", earlier, "early")
    _make_pending(db, "ev1", later, "late")
    rows = fetch_overdue_pending(db)
    # one row per event, the earliest one
    assert len(rows) == 1
    assert rows[0]["scan_id"] == sid_early


def test_l_fetch_skips_events_with_running_scan(db):
    fresh = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    _make_pending(db, "ev1", fresh)
    # Inject a running row for the same event
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, trigger_source) "
        "VALUES ('running1', 'analyze', 'ev1', ?, 'running', 'manual')",
        (datetime.now(UTC).isoformat(),),
    )
    db.conn.commit()
    assert fetch_overdue_pending(db) == []


def test_m_fetch_honors_custom_stale_threshold(db):
    # 45-minute-overdue should dispatch when threshold is bumped to 60 min.
    sched = (datetime.now(UTC) - timedelta(minutes=45)).isoformat()
    sid = _make_pending(db, "ev1", sched)
    # Default threshold (30min) — should be filtered out as stale
    assert fetch_overdue_pending(db) == []
    # Custom threshold (60min) — should dispatch
    rows = fetch_overdue_pending(db, stale_threshold_minutes=60)
    assert len(rows) == 1
    assert rows[0]["scan_id"] == sid


# ---------- n, o: one-shot migration ----------

def test_n_migration_converts_plus0800_to_plus0000(tmp_path):
    """Existing rows with +08:00 suffix should be migrated to +00:00 on db init."""
    db_path = tmp_path / "mig.db"

    # Build a DB at the current schema, then directly insert a row with a
    # non-UTC suffix to simulate historical data written before A.4.3.
    db = PolilyDB(db_path)
    upsert_event(EventRow(event_id="ev1", title="t", updated_at="now"), db)
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, "
        "trigger_source, scheduled_at) VALUES "
        "('legacy_bj', 'analyze', 'ev1', ?, 'pending', 'scheduled', "
        "'2026-05-01T18:00:00+08:00')",
        (datetime.now(UTC).isoformat(),),
    )
    db.conn.commit()
    db.close()

    # Reopen — migration should normalize the legacy row.
    db2 = PolilyDB(db_path)
    row = db2.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE scan_id='legacy_bj'"
    ).fetchone()
    db2.close()
    assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"


def test_o_migration_idempotent_on_already_utc(tmp_path):
    """If all rows are already +00:00, migration should be a no-op."""
    db_path = tmp_path / "mig2.db"
    db = PolilyDB(db_path)
    upsert_event(EventRow(event_id="ev1", title="t", updated_at="now"), db)
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, "
        "trigger_source, scheduled_at) VALUES "
        "('clean_utc', 'analyze', 'ev1', ?, 'pending', 'scheduled', "
        "'2026-05-01T10:00:00+00:00')",
        (datetime.now(UTC).isoformat(),),
    )
    db.conn.commit()
    db.close()

    db2 = PolilyDB(db_path)
    row = db2.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE scan_id='clean_utc'"
    ).fetchone()
    db2.close()
    assert row["scheduled_at"] == "2026-05-01T10:00:00+00:00"


# ---------- p, q, r, s: R3 round-2 follow-ups ----------

def test_p_v070_migration_ordering_seeds_get_utc_normalized(tmp_path):
    """Pin invariant: v0.7.0 migration (which seeds scan_logs.scheduled_at
    from event_monitors.next_check_at) runs BEFORE the UTC normalization
    migration. If the order ever flips silently, Beijing-locale users
    upgrading from <v0.7.0 would re-introduce the original Issue A bug.

    Approach: build a current-shape DB via PolilyDB, then mutate scan_logs
    and event_monitors back to pre-v0.7.0 shape (drop scheduled_at on
    scan_logs, add next_check_at on event_monitors). Reopen via PolilyDB
    → both migrations should run and the seeded row should land in
    scan_logs as +00:00.
    """
    db_path = tmp_path / "v070_mig.db"

    # Step 1: open once to get the standard, fully-formed schema.
    db = PolilyDB(db_path)
    upsert_event(EventRow(event_id="ev_bj", title="Beijing event",
                          updated_at=datetime.now(UTC).isoformat()), db)

    # Step 2: rewind scan_logs and event_monitors to pre-v0.7.0 shape so
    # the next PolilyDB open re-triggers _migrate_v070_scheduler.
    db.conn.executescript("""
        DROP TABLE scan_logs;
        CREATE TABLE scan_logs (
            scan_id TEXT PRIMARY KEY,
            type TEXT NOT NULL DEFAULT 'scan',
            event_id TEXT,
            market_title TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            total_elapsed REAL NOT NULL DEFAULT 0.0,
            status TEXT NOT NULL DEFAULT 'running',
            error TEXT,
            total_markets INTEGER NOT NULL DEFAULT 0,
            research_count INTEGER NOT NULL DEFAULT 0,
            watchlist_count INTEGER NOT NULL DEFAULT 0,
            filtered_count INTEGER NOT NULL DEFAULT 0,
            steps TEXT
        );
        ALTER TABLE event_monitors ADD COLUMN next_check_at TEXT;
        ALTER TABLE event_monitors ADD COLUMN next_check_reason TEXT;
    """)
    db.conn.execute(
        "INSERT INTO event_monitors "
        "(event_id, auto_monitor, next_check_at, next_check_reason, updated_at) "
        "VALUES (?, 1, ?, ?, ?)",
        ("ev_bj", "2026-05-01T18:00:00+08:00",
         "scheduled by Beijing-locale agent",
         datetime.now(UTC).isoformat()),
    )
    db.conn.commit()
    db.close()

    # Step 3: reopen — _init_schema runs both migrations in order.
    db2 = PolilyDB(db_path)
    rows = db2.conn.execute(
        "SELECT scheduled_at FROM scan_logs WHERE event_id='ev_bj'"
    ).fetchall()
    db2.close()

    # Exactly one seeded row; the +08:00 source must land as canonical UTC.
    assert len(rows) == 1
    assert rows[0]["scheduled_at"] == "2026-05-01T10:00:00+00:00", (
        f"Expected v0.7.0 seed row to be UTC-normalized after _init_schema; "
        f"got {rows[0]['scheduled_at']!r}. If this fails, check that "
        f"_migrate_scheduled_at_to_utc still runs after _migrate_v070_scheduler."
    )


def test_q_min_picks_time_earliest_not_lex_smallest(db):
    """Whis #1: CTE's MIN(scheduled_at) must compare by parsed time, not raw text.

    Setup: same event has TWO pending rows, one written via raw INSERT with
    +08:00 (bypassing A.4.3 normalize, simulating an admin script or
    pre-migration row that escaped the sweep). The +08:00 row's underlying
    UTC time is EARLIER than the +00:00 row, but lex-compare reverses that
    order. fetch_overdue_pending must return the time-earliest row.
    """
    now_utc = datetime.now(UTC)
    # Beijing row corresponds to time = now - 20 min UTC
    bj_dt = (now_utc - timedelta(minutes=20)).astimezone(timezone(timedelta(hours=8)))
    bj_iso = bj_dt.isoformat()  # ends with "+08:00"
    # UTC row at time = now - 5 min (later than bj_dt)
    utc_iso = (now_utc - timedelta(minutes=5)).isoformat()

    # Raw INSERT to bypass A.4.3 (insert_pending_scan would normalize).
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, "
        "trigger_source, scheduled_at) VALUES "
        "('bj_early', 'analyze', 'ev1', ?, 'pending', 'scheduled', ?)",
        (now_utc.isoformat(), bj_iso),
    )
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, "
        "trigger_source, scheduled_at) VALUES "
        "('utc_late', 'analyze', 'ev1', ?, 'pending', 'scheduled', ?)",
        (now_utc.isoformat(), utc_iso),
    )
    db.conn.commit()

    rows = fetch_overdue_pending(db)
    # Expected: exactly one row per event = the time-earliest one (bj_early,
    # which is 20 min ago UTC). Without datetime() wrap on MIN, raw text MIN
    # picks utc_late ("...+00:00" < "...+08:00" lexicographically).
    assert len(rows) == 1
    assert rows[0]["scan_id"] == "bj_early", (
        f"Expected time-earliest (bj_early), got {rows[0]['scan_id']!r}. "
        f"This means MIN() is text-ordered, not parsed-time-ordered."
    )


def test_r_raw_beijing_insert_is_overdue_via_sql_datetime(db):
    """Whis #3: raw INSERT bypassing write-boundary normalize still gets
    correctly classified as overdue by the SQL `datetime()` wrap in WHERE.

    Without the datetime() wrap, a +08:00 string at time = now - 10 min
    would lex-compare as greater than UTC `now()` and be invisible to the
    dispatcher. This test pins the SQL TZ-parsing layer directly (whereas
    test_h goes through insert_pending_scan which pre-normalizes).
    """
    # Build a +08:00 string for a time 10 minutes ago in UTC.
    overdue = (datetime.now(UTC) - timedelta(minutes=10)).astimezone(
        timezone(timedelta(hours=8))
    )
    overdue_iso = overdue.isoformat()  # "...+08:00"
    assert overdue_iso.endswith("+08:00")  # sanity

    # Raw INSERT — bypasses insert_pending_scan's UTC normalize (A.4.3).
    db.conn.execute(
        "INSERT INTO scan_logs(scan_id, type, event_id, started_at, status, "
        "trigger_source, scheduled_at) VALUES "
        "('raw_bj', 'analyze', 'ev1', ?, 'pending', 'scheduled', ?)",
        (datetime.now(UTC).isoformat(), overdue_iso),
    )
    db.conn.commit()

    rows = fetch_overdue_pending(db)
    assert len(rows) == 1
    assert rows[0]["scan_id"] == "raw_bj"
    # The stored value is still raw +08:00 (this test deliberately bypasses
    # A.4.5 too — it pins WHERE-clause SQL behavior, not the normalize
    # pipeline). The migration test_n already covers post-migration shape.
    assert rows[0]["scheduled_at"] == overdue_iso


def test_s_validate_handles_negative_tz_offset():
    """code-reviewer S1: cover negative TZ offsets in addition to Beijing/Z/naive.

    `-05:00` (US Eastern) lex-compares LOWER than `+00:00` (because '-' byte
    0x2D < '+' byte 0x2B), which would have caused the OPPOSITE failure
    mode of the Beijing bug — rows always classified as overdue including
    future-scheduled. Production fix uses datetime() SQL parsing which
    handles any offset uniformly; this test pins the write-boundary
    behavior for negative offsets symmetrically.
    """
    # 2026-05-01T05:00:00-05:00 == 2026-05-01T10:00:00+00:00 (same instant
    # as the +08:00 case in test_e — symmetric coverage).
    future_eastern = (datetime.now(UTC) + timedelta(hours=2)).astimezone(
        timezone(timedelta(hours=-5))
    )
    iso = future_eastern.isoformat()  # ends with "-05:00"
    assert iso.endswith("-05:00")  # sanity

    result = _validate_next_check_at(iso)
    assert result is not None
    assert result.endswith("+00:00")
    # Round-trip: parse the canonical result, re-format the input as UTC,
    # compare instants for equality (string equality may differ if the
    # microseconds component varies between platforms).
    parsed_result = datetime.fromisoformat(result)
    parsed_input = datetime.fromisoformat(iso)
    assert parsed_result == parsed_input
