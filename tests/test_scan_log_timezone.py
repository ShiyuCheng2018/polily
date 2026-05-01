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


def test_b_insert_normalizes_Z_suffix_to_plus0000(db):
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
